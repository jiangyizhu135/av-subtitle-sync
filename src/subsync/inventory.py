"""视频 / 字幕识别与番号解析（自包含，无 MDC/JavSP 依赖）。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".ts", ".m2ts"}
SUBTITLE_EXTS = {".srt", ".ass", ".ssa"}

# metadata sidecar（列出但不参与番号解析/字幕匹配之外的一切用途）
METADATA_SIDECAR_RE = re.compile(r"(\.nfo$|\.jpg$|\.jpeg$|\.png$|-poster\.png$|-backdrop\.png$)", re.IGNORECASE)

# 站点水印前缀：一般形为 `域名@`（如 forum.example.com@FileName.mp4）
JUNK_PREFIX_RE = re.compile(r"^[\w.-]+@", re.IGNORECASE)

# 番号 token：字母标签(2-6) + 可选分隔 + 数字(2-6)；前后不能是字母数字（防 SAVAGE 误配/超长数字）
TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{2,6})-?0*(\d{2,6})(?![A-Za-z0-9])", re.IGNORECASE)

_SUB_EXT_RE = re.compile(r"\.(srt|ass|ssa)$", re.IGNORECASE)


def is_video(name: str) -> bool:
    return PurePosixPath(name).suffix.lower() in VIDEO_EXTS


def is_subtitle_file(name: str) -> bool:
    return bool(_SUB_EXT_RE.search(name))


def is_metadata_sidecar(name: str) -> bool:
    return bool(METADATA_SIDECAR_RE.search(name))


@dataclass
class VideoEntry:
    rel: str                       # dav 根相对路径
    name: str
    size: int | None
    number: str | None = None
    subtitles: list[str] = field(default_factory=list)


def parse_number(filename: str) -> str | None:
    """视频文件名 → 番号（大写）；无法识别返回 None。

    规则（对现库 80 个视频与旧 pipeline 结果对齐）：
      1. 剥站点水印前缀（xxx@）
      2. 找第一个「字母标签+数字」token，数字后必须是边界（结尾/./-/_/CJK）
      3. 位数 ≤3 的数字保留原样（ABC-038）；≥4 位剥前导零（abc00499 → ABC-499）
    """
    s = JUNK_PREFIX_RE.sub("", filename)
    s = re.sub(r"\.(mp4|mkv|avi|mov|m4v|ts|m2ts)$", "", s, flags=re.IGNORECASE)
    m = TOKEN_RE.search(s)
    if not m:
        return None
    label, digits = m.group(1).upper(), m.group(2)
    # digits 已被 0* 前缀消费；恢复「≤3 位保留」语义：用原始匹配再取一次
    m2 = re.search(r"(?<![A-Za-z0-9])([A-Za-z]{2,6})-?(\d{2,6})(?![A-Za-z0-9])", s, re.IGNORECASE)
    if m2:
        label, raw_digits = m2.group(1).upper(), m2.group(2)
        if len(raw_digits) >= 4:
            digits = raw_digits.lstrip("0") or raw_digits
        else:
            digits = raw_digits
    return f"{label}-{digits}"


def subtitle_for(video_name: str, candidate_name: str) -> bool:
    """candidate 是否为 video 的已有字幕（同目录由调用方保证）。

    匹配（超集，宁多保护不误覆盖）：
      video.mp4  ←  video.mp4.srt / video.srt / video.zh-CN.srt /
                    video.mp4.zh-Hans.ass / video.chs.ssa …
    """
    if not is_subtitle_file(candidate_name):
        return False
    stem = video_name.rsplit(".", 1)[0]
    sub = candidate_name.lower()
    vlower = video_name.lower()
    sl = stem.lower()
    return sub.startswith(vlower + ".") or sub.startswith(sl + ".")


def build_inventory_entries(files: list) -> list[VideoEntry]:
    """由 dav 文件清单构建视频条目（含已有字幕关联与番号解析）。"""
    out: list[VideoEntry] = []
    by_dir: dict[str, list[str]] = {}
    for f in files:
        parent, _, name = f.rel.rpartition("/")
        by_dir.setdefault(parent, []).append(name)
    for f in files:
        if not is_video(f.rel):
            continue
        parent, _, name = f.rel.rpartition("/")
        subs = [c for c in by_dir.get(parent, []) if c != name and subtitle_for(name, c)]
        out.append(VideoEntry(rel=f.rel, name=name, size=f.size,
                              number=parse_number(name), subtitles=sorted(subs)))
    return out
