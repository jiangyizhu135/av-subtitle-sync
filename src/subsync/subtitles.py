"""字幕源 provider 与下载（本地缓存，禁止未审批 PUT）。

Provider: subtitlecat.com（实测直连可用；搜索页列出 /subs/<id>/<NAME>.html 详情页，
详情页直接暴露各语言 .srt 链接，如 /subs/1613/ABC-001-whisper-zh-CN-zh-CN.srt）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "Chrome/120 Safari/537.36")

# 语言偏好（越靠前越优先）
LANG_PREFERENCE = ["zh-CN", "zh-Hans", "zh", "chs", "zh-TW", "zh-Hant", "cht"]

# 已知语言码（用于从 "-<code>.srt" 后缀识别语言；长码优先防 "zh-CN" 被截成 "CN"）
_KNOWN_LANGS = sorted(
    ["zh-CN", "zh-Hans", "zh-TW", "zh-Hant", "pt-BR", "es-419",
     "en", "ja", "ko", "ar", "bn", "de", "fr", "es", "pt", "ru", "id", "th",
     "vi", "it", "nl", "pl", "tr", "zh", "chs", "cht", "big5", "gb", "he", "hi",
     "fa", "uk", "cs", "el", "ro", "hu", "sv", "da", "fi", "no", "ms", "tl"],
    key=len, reverse=True)

_SEARCH_URL = "https://www.subtitlecat.com/index.php?search={number}"
_BASE = "https://www.subtitlecat.com/"


@dataclass
class SubtitleCandidate:
    number: str
    detail_url: str
    title: str
    srt_url: str = ""
    language: str = ""          # 从 srt 文件名提取（如 zh-CN）
    languages: list = field(default_factory=list)   # 详情页全部语言（coverage 用）
    source: str = "subtitlecat"
    extra: dict = field(default_factory=dict)


def _session(settings=None):
    """字幕站对 Python TLS 指纹可能直接掐断连接（SSL UNEXPECTED_EOF）。
    统一经 http_backend（auto：curl 优先，Python 兜底）；settings 仅保留接口兼容。"""
    return


def _http_get(url: str, settings=None, timeout: int = 40, retries: int = 3) -> tuple[int, bytes]:
    """GET（经 HTTP backend：auto = curl 优先，Python 兜底）。

    返回 (http_status, body)。瞬态失败（TLS EOF 等）有限重试。
    URL 含空格/方括号/非 ASCII 时先做百分号编码（已编码的 %XX 不动）。
    """
    from urllib.parse import quote

    from subsync.http_backend import get_backend
    url = quote(url, safe="%/:=&?~#+!$,;'@()[]*")
    return get_backend("auto").get(url, timeout=timeout, retries=retries)


def search(number: str, settings=None) -> list[SubtitleCandidate]:
    """subtitlecat 搜索番号；返回详情页候选（标题含该番号者优先）。"""
    status, body = _http_get(_SEARCH_URL.format(number=number), settings)
    if status != 200 or not body:
        return []
    from lxml.html import fromstring
    lx = fromstring(body)
    pat = re.compile(rf"(?<![A-Za-z0-9]){re.escape(number)}(?![0-9])", re.IGNORECASE)
    out: list[SubtitleCandidate] = []
    seen = set()
    for a in lx.xpath('//a[@href]'):
        href = a.get("href") or ""
        text = (a.text_content() or "").strip()
        if "subs/" not in href or not href.endswith(".html"):
            continue
        if href in seen:
            continue
        seen.add(href)
        if not (pat.search(text) or pat.search(href)):
            continue
        url = href if href.startswith("http") else _BASE + href.lstrip("/")
        out.append(SubtitleCandidate(number=number, detail_url=url, title=text))
    return out


def _lang_of(fname: str) -> str:
    """从 "NAME-<lang>.srt" 识别语言码（已知码最长匹配；识别不出取最后一段）。"""
    if not fname.lower().endswith(".srt"):
        return ""
    base = fname[:-4]
    for code in _KNOWN_LANGS:
        if base.lower().endswith("-" + code.lower()) or base.lower().endswith("." + code.lower()):
            return base[-len(code):]
    m = re.search(r"-([A-Za-z0-9]+)$", base)
    return m.group(1) if m else ""


class SubtitleCatSource:
    """SubtitleSource adapter：subtitlecat.com（已验证可用；curl 后端 + 有限重试）。"""
    name = "subtitlecat"

    def search(self, number: str, settings=None) -> list[SubtitleCandidate]:
        return search(number, settings)

    def fetch_detail(self, candidate: SubtitleCandidate, settings=None) -> bool:
        return fetch_detail(candidate, settings)

    def download_srt(self, candidate: SubtitleCandidate, settings=None):
        return download_srt(candidate, settings)


# 已调研未启用的来源（覆盖率报告会如实记录）：
#   opensubtitles  — 需要 API key
#   assrt/zimuku   — 反爬/需登录
#   kitsunekko     — 动漫字幕站，不适用


def list_srts(detail_html: str) -> list[tuple[str, str]]:
    """详情页全部 (lang, srt_url)；语言码用已知码表识别（识别不出取最后一段）。"""
    from lxml.html import fromstring
    lx = fromstring(detail_html)
    out = []
    for a in lx.xpath('//a[@href]'):
        href = a.get("href") or ""
        if not re.search(r"/subs/[^\"']+\.srt$", href, re.IGNORECASE):
            continue
        fname = href.rsplit("/", 1)[-1]
        url = href if href.startswith("http") else _BASE + href.lstrip("/")
        out.append((_lang_of(fname), url))
    return out


def _pick_srt(detail_html: str) -> tuple[str, str] | None:
    """详情页里按语言偏好挑 .srt 链接，返回 (lang, absolute_url)。"""
    best: tuple[int, str, str] | None = None  # (pref_idx, lang, url)
    for lang, url in list_srts(detail_html):
        pref = len(LANG_PREFERENCE) + 100
        for i, p in enumerate(LANG_PREFERENCE):
            if lang.lower() == p.lower():
                pref = i
                break
        else:
            if lang.lower().startswith("zh"):
                pref = len(LANG_PREFERENCE)
        if best is None or pref < best[0]:
            best = (pref, lang, url)
    if best is None:
        return None
    return best[1], best[2]


def fetch_detail(candidate: SubtitleCandidate, settings=None) -> bool:
    """抓详情页并选出首选语言 srt 链接，填充 candidate.srt_url / language / languages。"""
    status, body = _http_get(candidate.detail_url, settings)
    if status != 200 or not body:
        return False
    html = body.decode("utf-8", errors="replace")
    candidate.languages = [lang for lang, _ in list_srts(html)]
    picked = _pick_srt(html)
    if not picked:
        return False
    candidate.language, candidate.srt_url = picked
    return True


def download_srt(candidate: SubtitleCandidate, settings=None) -> bytes | None:
    status, body = _http_get(candidate.srt_url, settings, timeout=60)
    if status == 200 and body:
        return body
    return None
