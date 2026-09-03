"""SRT 解析与验证。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_TS_RE = re.compile(
    r"(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})")


@dataclass
class SrtReport:
    ok: bool
    encoding: str = ""
    cue_count: int = 0
    empty_text_cues: int = 0
    bad_timestamp_cues: int = 0
    last_end: str = ""
    sample: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _decode(data: bytes) -> tuple[str, str]:
    from subsync.utils import normalize_newlines
    if data.startswith(b"\xef\xbb\xbf"):
        return normalize_newlines(data.decode("utf-8-sig")), "utf-8-sig"
    try:
        return normalize_newlines(data.decode("utf-8")), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return normalize_newlines(data.decode("gbk")), "gbk"
    except UnicodeDecodeError:
        return normalize_newlines(data.decode("utf-8", errors="replace")), "utf-8(replace)"


def validate_srt(data: bytes) -> SrtReport:
    text, enc = _decode(data)
    rep = SrtReport(ok=False, encoding=enc)
    blocks = re.split(r"\r?\n\r?\n+", text.strip())
    for b in blocks:
        lines = [ln for ln in b.splitlines() if ln.strip()]
        if not lines:
            continue
        ts_line = next((ln for ln in lines if "-->" in ln), None)
        if ts_line is None:
            rep.bad_timestamp_cues += 1
            continue
        m = _TS_RE.search(ts_line)
        if not m:
            rep.bad_timestamp_cues += 1
            continue
        text_lines = [ln for ln in lines[lines.index(ts_line) + 1:] if ln.strip()]
        if not text_lines:
            rep.empty_text_cues += 1
        else:
            rep.cue_count += 1
            rep.last_end = m.group(2)
            if len(rep.sample) < 3:
                rep.sample.append(" / ".join(text_lines)[:60])
    rep.errors = []
    if rep.cue_count == 0:
        rep.errors.append("无有效 cue")
    if rep.bad_timestamp_cues > 0 and rep.bad_timestamp_cues > rep.cue_count:
        rep.errors.append(f"时间轴行异常过多: {rep.bad_timestamp_cues}")
    # 空文本 cue（whisper 类自动字幕常见，纯时间轴无对白）只警告，不判失败；后续 PUT 轮可过滤
    rep.warnings = []
    if rep.empty_text_cues > 0:
        rep.warnings.append(f"{rep.empty_text_cues} 个 cue 无文本（时间轴-only）")
    rep.ok = rep.cue_count > 0 and not rep.errors
    return rep
