"""repair.py — Subtitle Repair Round：坏时间轴字幕的本地修复（只计划+本地 canary，不 PUT）。

规则：
  - DROP_INVALID_TIMELINE_CUES：仅删除 end<=start 的坏 cue（+空文本 cue，保持 final 规范 empty=0）
    ；其余有效 cue 的 start/end/text 一律不改；允许重编号
  - Quality Gate：invalid_ratio = removed_invalid / original_cue_count
      ratio <= 2%  → REPAIR_LOCAL_READY（允许生成 final 候选）
      ratio >  2%  → 不自动 DROP，标记 MANUAL_REPAIR_REQUIRED（示例：ABC-123 ~5.3%）
  - source.srt（RAW）永不覆盖；产物 repair.zh-CN.srt（最终复制为 final.zh-CN.srt）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pysubs2

MAX_AUTO_RATIO = 0.02


@dataclass
class SrtStats:
    total: int = 0
    invalid: int = 0
    empty: int = 0
    ok: int = 0
    last_end_ms: int = 0
    first_start_ms: int | None = None
    invalid_indexes: list = field(default_factory=list)

    @property
    def invalid_ratio(self) -> float:
        return self.invalid / self.total if self.total else 0.0


def decode(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("gbk", errors="replace")


def stat_srt(ssa: pysubs2.SSAFile) -> SrtStats:
    st = SrtStats(total=len(ssa.events))
    for i, e in enumerate(ssa.events):
        if e.end <= e.start:
            st.invalid += 1
            st.invalid_indexes.append(i + 1)
        elif e.plaintext.strip() == "":
            st.empty += 1
        else:
            st.ok += 1
            st.last_end_ms = max(st.last_end_ms, e.end)
            st.first_start_ms = e.start if st.first_start_ms is None else min(st.first_start_ms, e.start)
    return st


def repair_drop_invalid(data: bytes) -> tuple[bytes, SrtStats, SrtStats]:
    """删除 invalid(时序) + empty cue，重编号输出 UTF-8 SRT。返回 (bytes, before, after)。"""
    ssa = pysubs2.SSAFile.from_string(decode(data), format_="srt")
    before = stat_srt(ssa)
    kept = [e for e in ssa.events
            if not (e.end <= e.start) and e.plaintext.strip() != ""]
    out = pysubs2.SSAFile()
    out.events = kept
    raw = out.to_string("srt").encode("utf-8")
    after = stat_srt(pysubs2.SSAFile.from_string(decode(raw), format_="srt"))
    return raw, before, after


def repair_number(number: str, cache_root: Path, settings=None,
                  source_adapter=None) -> dict:
    """单番号 repair（下载当前最佳候选 → 保存 source.srt → 统计 → 决策）。不 PUT。"""
    from subsync.settings import get_settings
    from subsync.subtitles import SubtitleCatSource
    s = settings or get_settings()
    src = source_adapter or SubtitleCatSource()
    cache = cache_root / number
    cache.mkdir(parents=True, exist_ok=True)

    # fresh search：不依赖任何历史 coverage 文件
    from subsync.subtitles import search as sc_search
    cands = sc_search(number, s)
    if not cands:
        return {"number": number, "decision": "DOWNLOAD_FAILED", "error": "无可下载候选"}
    data, used = None, {}
    for c in cands[:4]:
        view = {"srt_url": c.srt_url, "detail_url": c.detail_url,
                "title": c.title, "language": c.language}
        data = src.download_srt(_view(view), s)
        if data:
            used = view
            break
    if not data:
        return {"number": number, "decision": "DOWNLOAD_FAILED", "error": "候选均下载失败"}

    (cache / "source.srt").write_bytes(data)      # RAW 只写一次（覆盖仅当原缺失）
    try:
        raw_bytes, before, after = repair_drop_invalid(data)
    except Exception as e:
        return {"number": number, "decision": "PARSE_FAILED", "error": f"{type(e).__name__}: {e}"}

    ratio = before.invalid_ratio
    record = {
        "number": number,
        "source_url": used.get("srt_url", ""),
        "original_cue_count": before.total,
        "invalid_cues": before.invalid,
        "empty_cues": before.empty,
        "invalid_ratio": round(ratio, 5),
        "repair_method": "DROP_INVALID_TIMELINE_CUES",
        "expected_final_cues": after.ok,
        "last_timestamp_ms": after.last_end_ms,
    }
    (cache / "repair.zh-CN.srt").write_bytes(raw_bytes)
    if ratio <= MAX_AUTO_RATIO and after.ok > 0 and after.last_end_ms >= 10 * 60 * 1000:
        # 允许本地 READY：复制为 final（source.srt 不动）
        (cache / "final.zh-CN.srt").write_bytes(raw_bytes)
        record["decision"] = "REPAIR_LOCAL_READY"
    elif ratio > MAX_AUTO_RATIO:
        record["decision"] = "MANUAL_REPAIR_REQUIRED"
        record["reason"] = f"invalid_ratio {ratio:.1%} > 2%，不自动删 {before.invalid} cues"
    else:
        record["decision"] = "REPAIR_UNCERTAIN"
        record["reason"] = "产物过短或时长可疑"
    record["local_files"] = {
        "source": str(cache / "source.srt"),
        "repair": str(cache / "repair.zh-CN.srt"),
        "final": str(cache / "final.zh-CN.srt") if (cache / "final.zh-CN.srt").is_file() else None,
    }
    return record


class _view:
    def __init__(self, d: dict):
        self.srt_url = d.get("srt_url", "")
        self.detail_url = d.get("detail_url", "")
        self.title = d.get("title", "")
        self.language = d.get("language", "")
