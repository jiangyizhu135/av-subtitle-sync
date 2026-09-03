"""variants.py v2 — 同番号多视频的正式分组模型（Video Group Model V2）。

六种分组（判定优先级从高到低）：
  1. MULTIPART                part/cd/disc/_n_ 分片 → 绝不允许整片字幕 fan-out
  2. VIDEO_VARIANT_GROUP      同作品不同清晰度（_4K/_8K/1080P/…）→ 允许同一 final SRT fan-out
  3. DUPLICATE_COPY_GROUP     历史重复副本（normalized basename 相同 + size 相同[+hash 相同]）
                             → 允许 fan-out 到每个副本目录
  4. EDITION_VARIANT_GROUP    番号 + edition 后缀（当前已知：-U）→ 可能是不同 edition，
                             timeline equivalence = UNKNOWN；standard 可传，edition variant
                             须 approve-variant 后才可传
  5. AMBIGUOUS                以上规则无法解释

Number Normalization != Timeline Equivalence：
  番号解析归一 ≠ 两个视频可共享字幕；本分类器与 number_parser 是两个独立层。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from subsync.inventory import JUNK_PREFIX_RE

# ---- 分片标记（优先级最高；即使同时带 8k 也仍是 MULTIPART）----
MULTIPART_RE = re.compile(r"(?:part|cd|disc)[ _\-]?(\d)", re.IGNORECASE)
_SOLO_DIGIT_RE = re.compile(r"_\d(_|$)")

# ---- 清晰度后缀（大小写不敏感）----
QUALITY_SUFFIXES = {"4K", "8K", "2160P", "1080P", "1080I", "720P", "HD", "FHD", "UHD"}

# ---- edition 后缀（保守：仅纳入已真实遇到且需区别处理的；不解释语义，U != uncensored 假设）----
EDITION_SUFFIXES = {"U"}

ROLES = ("STANDARD", "EDITION_VARIANT_UNRESOLVED")


def is_multipart_name(name: str) -> bool:
    stem = JUNK_PREFIX_RE.sub("", PurePosixPath(name).stem)
    return bool(MULTIPART_RE.search(stem) or _SOLO_DIGIT_RE.search(stem))


def _stem_of(name: str) -> str:
    return JUNK_PREFIX_RE.sub("", PurePosixPath(name).stem)


@dataclass
class VariantGroup:
    kind: str                       # SINGLE / VIDEO_VARIANT_GROUP / DUPLICATE_COPY_GROUP /
                                    # EDITION_VARIANT_GROUP / MULTIPART / AMBIGUOUS
    number: str
    variants: list = field(default_factory=list)
    # variant entry: {video_name, rel, size, quality, role, subtitle_name,
    #                 subtitle_upload_allowed, content_hash_verified}
    copy_count: int = 0
    edition_suffix: str = ""
    content_hash_verified: bool = False
    residual_suffixes: list = field(default_factory=list)
    reason: str = ""

    @property
    def uploadable(self) -> bool:
        """番号级：是否存在允许上传的 variant（batch 仍会逐 variant fresh 保护）。"""
        return self.kind in ("SINGLE", "VIDEO_VARIANT_GROUP", "DUPLICATE_COPY_GROUP") or \
            (self.kind == "EDITION_VARIANT_GROUP" and
             any(v.get("role") == "STANDARD" for v in self.variants))

    def to_json(self) -> dict:
        d = self.__dict__.copy()
        if self.kind != "DUPLICATE_COPY_GROUP":
            d.pop("content_hash_verified", None)
        if self.kind != "EDITION_VARIANT_GROUP":
            d.pop("edition_suffix", None)
        if self.kind not in ("DUPLICATE_COPY_GROUP", "EDITION_VARIANT_GROUP"):
            d.pop("copy_count", None)
        return d


def _variant_entry(v: dict, quality: str, role: str, subtitle_allowed: bool) -> dict:
    return {
        "video_name": v["name"], "rel": v["rel"], "size": v.get("size"),
        "quality": quality, "role": role,
        "subtitle_name": PurePosixPath(v["name"]).stem + ".srt",
        "subtitle_upload_allowed": subtitle_allowed,
        "content_hash_verified": False,
    }


def classify_number_videos(number: str, videos: list[dict]) -> VariantGroup:
    """videos: [{name/rel/size}]（同 canonical NUMBER）。"""
    g = VariantGroup(kind="AMBIGUOUS", number=number)
    if not videos:
        g.reason = "no videos"
        return g
    if any(is_multipart_name(v["name"]) for v in videos):
        g.kind = "MULTIPART"
        g.reason = "分片标记（part/cd/disc/_n_）优先于清晰度/edition 判定"
        return g
    if len(videos) == 1:
        g.kind = "SINGLE"
        g.variants = [_variant_entry(videos[0], "", "STANDARD", True)]
        return g

    num_re = re.compile(
        rf"^{re.escape(number)}(?:[_\-\. ](?P<suffix>[A-Za-z0-9]+))?$", re.IGNORECASE)
    parsed = []
    residual: list[str] = []
    for v in videos:
        stem = _stem_of(v["name"])
        m = num_re.match(stem)
        if not m:
            g.reason = f"文件名无法解释为 {number}[+后缀]: {v['name']}"
            g.residual_suffixes = residual
            return g
        suffix = m.group("suffix")
        if suffix is None:
            kind_s = "plain"
        elif suffix.upper() in QUALITY_SUFFIXES:
            kind_s = "quality"
        elif suffix.upper() in EDITION_SUFFIXES:
            kind_s = "edition"
        else:
            residual.append(suffix)
            g.reason = f"未知后缀 '{suffix}'（{v['name']}）——可能是不同 edition，无法保证时间轴一致"
            g.residual_suffixes = residual
            return g
        parsed.append({"v": v, "kind": kind_s, "suffix": suffix,
                       "quality": suffix.upper() if kind_s == "quality" else "",
                       "stem": stem.lower()})

    kinds = {p["kind"] for p in parsed}
    if "quality" in kinds and "edition" in kinds:
        g.reason = "quality 与 edition 后缀混合出现，无法归入单一模型"
        return g

    # ---- quality-only → VIDEO_VARIANT_GROUP（要求组合互异；重复组合交给 duplicate 判定）----
    if kinds <= {"plain", "quality"} and "quality" in kinds:
        combos = [(p["stem"], p["quality"]) for p in parsed]
        if len(set(combos)) != len(combos):
            g.reason = "存在完全相同的 stem+清晰度组合（疑似重复副本混合 variant）"
            return g
        g.kind = "VIDEO_VARIANT_GROUP"
        g.variants = [_variant_entry(p["v"], p["quality"], "STANDARD", True) for p in parsed]
        g.variants.sort(key=lambda x: (x["quality"] != "", x["quality"]))
        return g

    # ---- edition（可含 plain）→ EDITION_VARIANT_GROUP ----
    if "edition" in kinds:
        g.kind = "EDITION_VARIANT_GROUP"
        g.edition_suffix = next(p["suffix"].upper() for p in parsed if p["kind"] == "edition")
        for p in parsed:
            role = "STANDARD" if p["kind"] == "plain" else "EDITION_VARIANT_UNRESOLVED"
            g.variants.append(_variant_entry(p["v"], p["quality"] if p["kind"] == "quality" else "",
                                             role, role == "STANDARD"))
        g.variants.sort(key=lambda x: (x["role"] != "STANDARD", x["video_name"]))
        g.reason = f"edition 后缀 '-{g.edition_suffix}'（timeline equivalence = UNKNOWN）"
        return g

    # ---- 全部 plain（多视频）→ 历史重复副本判定 ----
    stems = {p["stem"] for p in parsed}
    sizes = {p["v"].get("size") for p in parsed}
    if len(stems) == 1 and len(sizes) == 1:
        g.kind = "DUPLICATE_COPY_GROUP"
        g.copy_count = len(parsed)
        g.content_hash_verified = False     # inventory 无 etag/hash，不声称字节级确认
        g.variants = [_variant_entry(p["v"], "", "STANDARD", True) for p in parsed]
        g.reason = (f"{len(parsed)} 个历史副本（normalized basename 与 size 一致；"
                    "content_hash_verified=false——未做字节级确认）")
        return g

    g.reason = (f"多视频但 basename/size 不一致且无后缀可解释 "
                f"(stems={sorted(stems)}, sizes={sorted(str(x) for x in sizes)})")
    return g
