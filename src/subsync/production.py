"""production.py — Round 4A：本地最终简中 SRT 生产（零远端写）。

规则（对齐 Round 4 规格）：
  - Exact Number Gate：下载前后都校验候选 == canonical NUMBER（词边界），否则 NUMBER_MATCH_FAILED
  - Raw 保留：data/subtitle_cache/<NUM>/source.srt + source_meta.json（url/lang/format/sha256/at）
  - Parse 校验：pysubs2 可解析、cue>0、start<end、非 HTML/错误页/登录页
  - 空 cue 清理：删 text.strip()==""，其余 cue 的 start/end/text 一律不动
  - zh-CN direct：正文零修改；zh-TW：OpenCC t2s 逐 cue 只改 text（TIMELINE_MUTATED 守卫）
  - Final：final.zh-CN.srt，UTF-8 SRT，reopen empty==0；时长 sanity（<10min → SUSPICIOUS）
  - 本模块绝不触碰 WebDAV PUT
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

import pysubs2

from subsync.clean import load_srt

MIN_SUSPECT_MS = 10 * 60 * 1000


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# exact-number gate 允许的番号后缀（同一影片的版本标签，非相邻番号）：
# "ABC-123uc"/"ABC-123-C" 这类；数字尾缀（8550）永远不允许
_SUFFIX_OK_RE = re.compile(
    r"^(?:" + "|".join(["uc", "c", "u", "cs", "uncensored", "censored", "leaked", "leak",
                        "restored", "remastered", "hd", "fhd", "4k", "8k", "cd1", "cd2", "cd3",
                        "part1", "part2", "part3", "eng", "jp", "ja", "zh", "subs", "sub"]) + r")$", re.IGNORECASE)


def exact_number_match(number: str, *texts: str) -> bool:
    """候选文本包含 canonical NUMBER：
      1) 词边界严格匹配；或
      2) NUMBER 后跟白名单版本后缀（ABC-123uc = 同片版本后缀），数字尾缀仍拒绝。
    """
    pat_strict = re.compile(rf"(?<![A-Za-z0-9]){re.escape(number)}(?![A-Za-z0-9])", re.IGNORECASE)
    pat_suffix = re.compile(
        rf"(?<![A-Za-z0-9]){re.escape(number)}-?([A-Za-z]{{1,12}})(?![A-Za-z0-9])", re.IGNORECASE)
    for t in texts:
        t = unquote(t or "")
        if pat_strict.search(t):
            return True
        m = pat_suffix.search(t)
        if m and _SUFFIX_OK_RE.match(m.group(1)):
            return True
    return False


@dataclass
class ProduceResult:
    number: str
    status: str = "PENDING"            # LOCAL_READY / *_FAILED / SUSPICIOUS_SUBTITLE_DURATION / SKIPPED_*
    error: str = ""
    source_url: str = ""
    source_language: str = ""
    source_format: str = "srt"
    source_sha256: str = ""
    downloaded_at: str = ""
    original_cue_count: int = 0
    empty_cues_removed: int = 0
    cue_count: int = 0
    first_timestamp: str = ""
    last_timestamp: str = ""
    sha256_final: str = ""
    translated: bool = False
    converted: bool = False
    sparse_subtitle_warning: bool = False   # cue_count < 50 → MANUAL_REVIEW_WARNING
    video_rels: list = field(default_factory=list)

    def to_json(self) -> dict:
        return self.__dict__.copy()


def _decode(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("gbk", errors="replace")


def looks_like_error_page(text: str) -> bool:
    """错误页/HTML 检测。标记必须足够特异（毫秒字段里会出现 '404' 数字，不能用裸 404）。"""
    low = text[:4000].lower()
    html_markers = ("<html", "<!doctype", "<div", "<script", "<body")
    page_markers = ("page not found", "error 404", "just a moment", "enable javascript",
                    "checking your browser", "cf-browser-verification", "sign in to continue")
    return any(m in low for m in html_markers) or any(m in low for m in page_markers)


def validate_raw_srt(data: bytes) -> tuple[pysubs2.SSAFile | None, str]:
    """返回 (ssa, "") 或 (None, 失败原因)。"""
    if not data or len(data) < 32:
        return None, "EMPTY_DOWNLOAD"
    text = _decode(data)
    if looks_like_error_page(text):
        return None, "ERROR_PAGE_CONTENT"
    try:
        ssa = pysubs2.SSAFile.from_string(text, format_="srt")
    except Exception as e:
        return None, f"PARSE_FAILED:{type(e).__name__}"
    events = ssa.events
    if not events:
        return None, "NO_CUES"
    for e in events:
        if e.end <= e.start:
            return None, "START_GE_END"
    return ssa, ""


def clean_events(ssa: pysubs2.SSAFile):
    """删空文本 cue；返回 (kept_events, removed)。有效 cue 的 start/end/text 不动。"""
    kept = [e for e in ssa.events if e.plaintext.strip() != ""]
    return kept, len(ssa.events) - len(kept)


def build_final(kept, converted: bool = False) -> bytes:
    out = pysubs2.SSAFile()
    out.events = kept
    return out.to_string("srt").encode("utf-8")


def _ts(ms: int) -> str:
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, milli = divmod(rem, 1000)
    return f"{h}:{m:02d}:{s:02d}.{milli:03d}"


def opencc_convert_events(kept):
    """OpenCC t2s 逐 cue 只改 text；时间轴逐一比对，任何变化抛 TIMELINE_MUTATED。"""
    from opencc import OpenCC
    cc = OpenCC("t2s")
    before = [(e.start, e.end) for e in kept]
    converted = []
    for e in kept:
        ne = pysubs2.SSAEvent(start=e.start, end=e.end, text=cc.convert(e.text))
        converted.append(ne)
    after = [(e.start, e.end) for e in converted]
    if before != after:
        raise RuntimeError("TIMELINE_MUTATED")
    return converted


def produce_number(number: str, coverage_entry: dict, cache_root: Path,
                   settings=None, source_adapter=None) -> ProduceResult:
    """单番号生产：候选迭代（门禁→下载→验证），首个成功者生效。全程本地。"""
    from subsync.subtitles import SubtitleCatSource
    res = ProduceResult(number=number)
    src = source_adapter or SubtitleCatSource()

    best = (coverage_entry or {}).get("best_candidate") or {}
    others = (coverage_entry or {}).get("candidates") or []
    # 候选迭代顺序：best 优先，其余按 coverage 顺序；逐个过门禁
    seen = set()
    cand_list = []
    for c in [best] + [o for o in others]:
        if not c or not c.get("detail_url") or c["detail_url"] in seen:
            continue
        seen.add(c["detail_url"])
        cand_list.append(c)
    if not cand_list:
        res.status = "COVERAGE_MISSING_BEST"
        res.error = "coverage 无候选"
        return res

    attempts = []
    for cand in cand_list[:3]:                   # 最多尝试 3 个候选
        # ---- Exact Number Gate（production 阶段二次校验）----
        if not exact_number_match(number, cand.get("detail_url", ""), cand.get("title", ""),
                                  cand.get("srt_url", "")):
            attempts.append({"candidate": cand.get("title"), "result": "NUMBER_MATCH_FAILED"})
            continue
        # ---- 下载 raw（错误页/空下载为瞬态故障：有限重试）----
        data, ssa, err = None, None, ""
        for attempt in range(3):
            data = src.download_srt(_CandView(cand), settings)
            if data:
                ssa, err = validate_raw_srt(data)
                if ssa is not None or err != "ERROR_PAGE_CONTENT":
                    break
            time.sleep(2.0 + attempt * 2)
        if not data:
            attempts.append({"candidate": cand.get("title"), "result": "DOWNLOAD_FAILED"})
            continue
        if ssa is None:
            attempts.append({"candidate": cand.get("title"), "result": f"INVALID:{err}"})
            continue

        cache = cache_root / number
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "source.srt").write_bytes(data)
        res.source_url = cand.get("srt_url", "")
        res.source_language = cand.get("language", "")
        res.source_format = "srt"
        res.source_sha256 = sha256(data)
        res.downloaded_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (cache / "source_meta.json").write_text(json.dumps({
            "source_url": res.source_url, "source_language": res.source_language,
            "source_format": res.source_format, "source_sha256": res.source_sha256,
            "downloaded_at": res.downloaded_at, "attempts": attempts,
        }, ensure_ascii=False, indent=1), encoding="utf-8")

        # ---- 清理空 cue ----
        kept, removed = clean_events(ssa)
        if not kept:
            res.status = "INVALID_SUBTITLE"
            res.error = "清理后无有效 cue"
            return res
        res.original_cue_count = len(ssa.events)
        res.empty_cues_removed = removed

        # ---- 语言处理 ----
        lang = (res.source_language or "").lower()
        try:
            if lang in ("zh-tw", "zh-hant", "cht", "big5"):
                kept = opencc_convert_events(kept)
                res.converted = True
            elif lang.startswith("zh") or lang in ("chs", "gb"):
                pass  # zh-CN direct：正文零修改
            else:
                res.status = "LANGUAGE_NOT_AUTO_HANDLED"
                res.error = f"source_language={res.source_language}（需要翻译，production 不自动处理）"
                return res
        except RuntimeError as e:
            res.status = str(e)                  # TIMELINE_MUTATED
            res.error = str(e)
            return res

        # ---- final ----
        final_bytes = build_final(kept, converted=res.converted)
        (cache / "final.zh-CN.srt").write_bytes(final_bytes)

        # ---- reopen 验证 ----
        try:
            reopened = load_srt(final_bytes)
        except Exception as e:
            res.status = "REOPEN_FAILED"
            res.error = f"{type(e).__name__}: {e}"[:100]
            return res
        empty_after = sum(1 for e in reopened.events if e.plaintext.strip() == "")
        if empty_after != 0 or len(reopened.events) != len(kept):
            res.status = "REOPEN_MISMATCH"
            res.error = f"empty={empty_after} cues={len(reopened.events)}"
            return res

        res.cue_count = len(kept)
        res.first_timestamp = _ts(kept[0].start)
        res.last_timestamp = _ts(kept[-1].end)
        res.sha256_final = sha256(final_bytes)
        if kept[-1].end < MIN_SUSPECT_MS:
            res.status = "SUSPICIOUS_SUBTITLE_DURATION"
            res.error = f"last_timestamp={res.last_timestamp} (< 10min)"
        else:
            res.status = "LOCAL_READY"
        return res

    # 全部候选失败：取首个明确原因
    res.status = "ALL_CANDIDATES_FAILED"
    res.error = json.dumps(attempts, ensure_ascii=False)[:400]
    return res


class _CandView:
    """让 source.download_srt 复用 SubtitleCandidate 下载路径（鸭子类型）。"""

    def __init__(self, best: dict):
        self.srt_url = best.get("srt_url", "")
        self.detail_url = best.get("detail_url", "")
        self.title = best.get("title", "")
        self.language = best.get("language", "")
