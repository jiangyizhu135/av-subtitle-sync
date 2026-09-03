"""deep_search.py — Full Library Deep Subtitle Search（多来源、只搜索/缓存，Remote PUT=0）。

Source Result Schema（统一）：
  {number, source, page_url, indexed, downloadable, access_type,
   languages[], format, source_filename, runtime_minutes, exact_number_match, notes[]}

access_type ∈ {FREE_DIRECT, LOGIN_REQUIRED, CAPTCHA_REQUIRED, PAID_ONLY,
               DONATION_REQUIRED, JS_SHELL, INDEXED_BUT_NOT_DOWNLOADABLE, UNREACHABLE}

已有 VERIFIED/UPLOADED 字幕绝不触碰；发现更优仅记 notes。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import quote

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "Chrome/120 Safari/537.36")

# ---- 能力探测结果（2026-09-03 实测）----
SOURCE_CAPABILITY = {
    "subtitletrans": {"access_type": "CAPTCHA_REQUIRED",
                      "note": "Cloudflare JS challenge（403 'Just a moment'）；页面存在性无法可靠确认"},
    "opensubtitles": {"access_type": "LOGIN_REQUIRED",
                      "note": "401；需账号/API key"},
    "subdivx":       {"access_type": "CAPTCHA_REQUIRED", "note": "403"},
    "javsubs.co":    {"access_type": "JS_SHELL", "note": "页面为 JS 壳（~1KB），无静态搜索结果"},
    "subtitlex.com": {"access_type": "UNREACHABLE", "note": "首页仅 114B（异常）"},
}

# 已知语言词（页面语言列/文件名识别）
_LANG_PRI = {"zh-cn": 0, "zh-hans": 0, "chs": 0, "zh-tw": 1, "zh-hant": 1, "cht": 1,
             "zh": 2, "en": 3, "ja": 4}
_LANG_PRI = {"zh-cn": 0, "zh-hans": 0, "chs": 0, "zh-tw": 1, "zh-hant": 1, "cht": 1,
             "zh": 2, "en": 3, "ja": 4}
_LANG_WORDS = {"english": "en", "chinese": "zh", "japanese": "ja", "korean": "ko",
               "vietnamese": "vi", "spanish": "es", "french": "fr", "german": "de",
               "zh-cn": "zh-CN", "zh-tw": "zh-TW", "simplified chinese": "zh-CN",
               "traditional chinese": "zh-TW"}


def query_variants(number: str, edition: str | None = None, parts: list | None = None) -> list[str]:
    """合法 query 变体。回归 canonical 由 number gate 保证。"""
    base = [number, number.replace("-", "")]
    m = re.match(r"^([A-Za-z]{2,6})-(\d+)$", number)
    if m:
        label, digits = m.group(1), m.group(2)
        if len(digits) >= 4:
            base.append(f"{label.lower()}{digits}")   # sivr00499 形式
    if edition:
        base += [f"{number}-{edition}", f"{number} {edition}", f"{number}-{edition}C"]
    if parts:
        for p in parts:
            base += [f"{number} {p}", f"{number} {p.upper()}", f"{number}-{p}"]
    return list(dict.fromkeys(base))


def number_gate(number: str, text: str) -> bool:
    """strict：word-boundary canonical 或 canonical+已知版本尾缀（数字尾缀拒绝）。"""
    pat = re.compile(rf"(?<![A-Za-z0-9]){re.escape(number)}(?![A-Za-z0-9])", re.IGNORECASE)
    return bool(pat.search(text))


# ================================================================ 各 source 实现（独立隔离）
def fetch(url: str, timeout: int = 25) -> tuple[int, bytes]:
    """HTTP GET（auto backend：curl 优先 / Python 兜底）。"""
    from subsync.http_backend import get_backend
    return get_backend("auto").get(quote(url, safe="%/:=&?~#+!$,;'@()[]*"), timeout=timeout)


def subtitlecat_lookup(number: str, settings) -> list[dict]:
    """复用已验证 adapter：search → 详情页语言/可下载。"""
    from subsync.subtitles import fetch_detail
    from subsync.subtitles import search as sc_search
    out = []
    try:
        cands = sc_search(number, settings)
    except Exception as e:
        return [{"source": "subtitlecat", "indexed": False, "downloadable": False,
                 "access_type": "SOURCE_ERROR", "notes": [f"{type(e).__name__}: {e}"[:80]]}]
    if not cands:
        return [{"source": "subtitlecat", "indexed": False, "downloadable": False,
                 "access_type": "NOT_INDEXED", "exact_number_match": None, "languages": []}]
    seen = set()
    entries = []
    for c in cands[:3]:
        if c.detail_url in seen:
            continue
        seen.add(c.detail_url)
        try:
            fetch_detail(c, settings)
        except Exception:
            pass
        langs = [lang for lang in (c.languages or [])]
        has_direct_srt = bool(c.srt_url)
        entries.append({
            "source": "subtitlecat", "page_url": c.detail_url,
            "indexed": True, "downloadable": has_direct_srt,
            "access_type": "FREE_DIRECT" if has_direct_srt else "INDEXED_BUT_NOT_DOWNLOADABLE",
            "languages": langs, "format": "srt", "source_filename": "",
            "srt_url": c.srt_url or "",
            "runtime_minutes": None, "exact_number_match": number_gate(number, c.detail_url),
            "notes": [],
        })
        time.sleep(0.3)
    out.extend(entries)
    return out


def avsubtitles_lookup(number: str) -> list[dict]:
    """avsubtitles.com：search → movie detail（语言/可下载性，下载通常需捐赠/登录）。"""
    try:
        code, body = fetch("https://avsubtitles.com/search_results.php?search=" + quote(number))
        if code != 200 or not body:
            return [{"source": "avsubtitles", "access_type": "UNREACHABLE" if code == 0 else f"HTTP{code}",
                     "indexed": False, "downloadable": False}]
        txt = body.decode("utf-8", errors="replace")
        if "no subtitles match" in txt:
            return [{"source": "avsubtitles", "indexed": False, "downloadable": False,
                     "access_type": "NOT_INDEXED", "languages": [], "exact_number_match": None}]
        mov = re.findall(r'href="(/movie\d+/[^"]*)"', txt)
        rows = []
        for u in list(dict.fromkeys(mov))[:2]:
            code2, b2 = fetch("https://avsubtitles.com" + u)
            if code2 != 200:
                rows.append({"source": "avsubtitles", "page_url": u, "indexed": True,
                             "downloadable": False, "access_type": f"HTTP{code2}", "languages": []})
                continue
            t2 = b2.decode("utf-8", errors="replace")
            langs = []
            # 详情页语言标记行（页面以 &nbsp;Chinese&nbsp; 形式列主语言，以及常见词）
            for word, code3 in _LANG_WORDS.items():
                if re.search(rf"(?:&nbsp;|>)\s*{word}\s*(?:&nbsp;|<)", t2, re.IGNORECASE) \
                        or re.search(rf">\s*{word}\s*<", t2, re.IGNORECASE):
                    langs.append(code3)
            langs = list(dict.fromkeys(langs))
            login = ("login.php" in t2)  # 详情页含 Donate/Login 时视为无免费直链
            rows.append({
                "source": "avsubtitles", "page_url": "https://avsubtitles.com" + u,
                "indexed": True, "downloadable": False,
                "access_type": "LOGIN_REQUIRED" if login else "INDEXED_BUT_NOT_DOWNLOADABLE",
                "languages": langs, "format": "srt", "source_filename": "",
                "runtime_minutes": None, "exact_number_match": number_gate(number, u),
                "notes": ["详情页列主语言；免费下载需登录/捐赠，未见直链"],
            })
            time.sleep(0.4)
        return rows
    except Exception as e:
        return [{"source": "avsubtitles", "indexed": False, "downloadable": False,
                 "access_type": "SOURCE_ERROR", "notes": [str(e)[:80]]}]


def gated_source_result(source: str) -> dict:
    cap = SOURCE_CAPABILITY.get(source, {})
    return {"source": source, "indexed": None, "downloadable": False,
            "access_type": cap.get("access_type", "UNKNOWN"),
            "languages": [], "notes": [cap.get("note", "")]}


def search_engine_discovery(number: str, edition: str | None = None, parts: list | None = None,
                            max_q: int = 2) -> list[dict]:
    """DDG HTML 发现候选 URL（仅记录，不作为可下载结论）。失败返回 []。"""
    out = []
    qs = query_variants(number, edition, parts)[:max_q]
    for q in qs:
        try:
            code, body = fetch("https://html.duckduckgo.com/html/?q=" + quote(f'"{q}" subtitle'))
            if code != 200:
                return []
            t = body.decode("utf-8", errors="replace")
            res = re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', t, re.DOTALL)
            for href, title in res[:4]:
                title = re.sub(r"<[^>]+>", "", title).strip()
                out.append({"query": q, "result_url": href[:200], "title": title[:120],
                            "number_gate": number_gate(number, href + " " + title)})
            time.sleep(1.2)
        except Exception:
            return []
    return out


# ================================================================ 全库驱动
# 多分片番号的 part 查询变体示例（按需在调用方提供）
EXAMPLE_MULTIPART_PARTS = {"ABC-123": ["part1", "part2"]}


def search_one(number: str, out_dir: Path, settings=None, use_engine: bool = False,
               parts: list | None = None) -> dict:
    """单番号全源扫描。返回 per-source 结果 dict。"""
    res: dict = {}
    # subtitlecat（真 adapter）
    res["subtitlecat"] = subtitlecat_lookup(number, settings)
    time.sleep(0.8)
    # avsubtitles（真 adapter）
    res["avsubtitles"] = avsubtitles_lookup(number)
    time.sleep(0.8)
    # 探测为 gated 的源：如实记录能力
    for src in ("subtitletrans", "opensubtitles", "subdivx", "javsubs.co", "subtitlex.com"):
        res[src] = gated_source_result(src)
    # 搜索引擎发现（fallback 记录）
    res["search_engine"] = search_engine_discovery(number, parts=parts) if use_engine else []
    # 汇总 best_candidate（供 produce 使用，按 zh-CN > zh-TW > zh > en > ja 排序优先）
    best = None
    for src in ("subtitlecat", "avsubtitles"):
        for row in res.get(src, []):
            if not (isinstance(row, dict) and row.get("downloadable")):
                continue
            langs = row.get("languages") or []
            pri = min((_LANG_PRI.get(lang.lower(), 90) for lang in langs), default=90)
            if best is None or pri < best[0]:
                best = (pri, {"source": src, "language": (langs[0] if langs else ""),
                              "languages": langs, "format": row.get("format") or "srt",
                              "exact_number_match": row.get("exact_number_match", True),
                              "page_url": row.get("page_url", ""),
                              "notes": ["downloadable per index; direct srt link pending"]})
    res["best_candidate"] = best[1] if best else None
    out_dir.mkdir(parents=True, exist_ok=True)
    for src, data in res.items():
        (out_dir / f"{src}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return res
