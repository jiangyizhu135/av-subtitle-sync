"""SRT 清理：删除纯时间轴空文本 cue（不改任何有效 cue 的 start/end/text），输出 UTF-8 SRT。

使用 pysubs2 作为唯一 parser/writer（加载 → 过滤 → 保存 → 重开验证）。
SRT 序号由 pysubs2 保存时自动重排（1..N），与时间轴无关。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pysubs2


@dataclass
class CleanReport:
    original_cue_count: int = 0
    empty_removed: int = 0
    final_cue_count: int = 0
    last_end_ms: int = 0
    first_start_ms: int | None = None
    sample_first: list = field(default_factory=list)   # (idx, start, end, text)
    sample_middle: list = field(default_factory=list)
    reopened_empty: int = 0                            # 保存后重开验证的空 cue 数（必须为 0）


def _ts(ms: int) -> str:
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms_ = divmod(rem, 1000)
    return f"{h}:{m:02d}:{s:02d}.{ms_:03d}"


def load_srt(data: bytes) -> pysubs2.SSAFile:
    from subsync.utils import normalize_newlines
    text = normalize_newlines(data.decode("utf-8-sig"))
    return pysubs2.SSAFile.from_string(text, format_="srt")


def clean_events(ssa: pysubs2.SSAFile):
    """删除 invalid（end<=start）与空文本 cue；其余 start/end/text 不动。
    返回 (kept_events, removed_count)。"""
    kept = [e for e in ssa.events if not (e.end <= e.start) and e.plaintext.strip() != ""]
    return kept, len(ssa.events) - len(kept)


def build_final(kept) -> bytes:
    """kept events → UTF-8 SRT bytes（pysubs2 自动重编号）。"""
    out = pysubs2.SSAFile()
    out.events = kept
    return out.to_string("srt").encode("utf-8")


def clean_srt(data: bytes) -> tuple[bytes, CleanReport, pysubs2.SSAFile]:
    """返回 (final_bytes, report, final_ssafile)。只删空文本 cue，其余原样。"""
    ssa = load_srt(data)
    rep = CleanReport()
    rep.original_cue_count = len(ssa.events)
    kept = [e for e in ssa.events if e.plaintext.strip() != ""]
    rep.empty_removed = rep.original_cue_count - len(kept)

    out = pysubs2.SSAFile()
    out.events = kept
    out.info = dict(ssa.info)
    out.styles = ssa.styles
    final_bytes = out.to_string("srt").encode("utf-8")

    rep.final_cue_count = len(kept)
    if kept:
        rep.first_start_ms = kept[0].start
        rep.last_end_ms = kept[-1].end

    # 重新打开验证（pysubs2 reopen）
    reopened = pysubs2.SSAFile.from_string(final_bytes.decode("utf-8"), format_="srt")
    rep.reopened_empty = sum(1 for e in reopened.events if e.plaintext.strip() == "")
    return final_bytes, rep, reopened


def sample_cues(ssa: pysubs2.SSAFile, n_first: int = 5, n_middle: int = 3) -> tuple[list, list]:
    """前 n_first 个 cue + 中部随机 n_middle 个。返回 ((idx,start,end,text), ...)。"""
    import random
    events = ssa.events
    first = [(i + 1, _ts(e.start), _ts(e.end), e.plaintext.replace("\\N", " ").replace("\n", " "))
             for i, e in enumerate(events[:n_first])]
    middle_pool = list(range(n_first, max(n_first, len(events) - n_first)))
    picks = sorted(random.Random(42).sample(middle_pool, min(n_middle, len(middle_pool)))) if middle_pool else []
    middle = [(i + 1, _ts(events[i].start), _ts(events[i].end),
               events[i].plaintext.replace("\\N", " ").replace("\n", " ")) for i in picks]
    return first, middle
