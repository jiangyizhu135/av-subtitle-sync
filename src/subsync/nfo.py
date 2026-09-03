"""NFO generation — Kodi/Jellyfin/VidHub compatible ``.nfo`` XML assembly.

Builds a movie NFO document from a metadata dict, a plot string and an
optional resolved-title record. Generation is pure and offline: no network
access, no scraping, no remote writes — callers decide where the bytes go.

Title policy (stable, do not change silently):
  <title>         = NUMBER + " " + display title (Simplified Chinese preferred,
                    falls back to the original title)
  <originaltitle> = original (e.g. Japanese) title as scraped
  <sorttitle>     = NUMBER
"""
from __future__ import annotations

import ast
import re
import xml.etree.ElementTree as ET
from typing import Any


def parse_list(v: Any) -> list[str]:
    """Normalize list-ish metadata values (None / list / "['a', 'b']" / str) to [str]."""
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v]
    if isinstance(v, str):
        s = v.strip()
        try:
            r = ast.literal_eval(s)
            return [str(x) for x in r] if isinstance(r, list) else [s]
        except Exception:
            return [s]
    return [str(v)]


def compose_nfo_title(num: str, base_title: str | None) -> str:
    """<title> = NUMBER + " " + 标题；若标题自身已以同番号开头则不重复拼接。

    兼容 MIDA-727 / MIDA727 / 数字前缀等写法，避免生成 "NUMBER NUMBER xxx"。
    """
    base = (base_title or "").strip()
    if not base:
        return num
    m = re.match(rf"^({re.escape(num)}|{re.escape(num.split('-')[0])}\s*\d{{2,6}})\s*[:：]?\s*", base, re.I)
    if m:
        base = base[m.end():].strip()
    return f"{num} {base}".strip()


def build_nfo_bytes(num: str, meta: dict[str, Any], plot: str | None,
                    thumb_map: dict[str, str] | None = None,
                    title_info: dict[str, Any] | None = None) -> bytes:
    """Assemble the NFO XML document as UTF-8 bytes (XML declaration included).

    meta: 刮削器输出的 metadata dict（number/cid/title/release/score/runtime/
          producer/director/actresses/genres/trailer，缺失字段自动跳过）。
    plot: 剧情简介；None 时 <plot>/<outline> 均不写入（绝不编造）。
    thumb_map: actress name → thumb URL（可选）。
    title_info: 可选标题解析结果，display_title 优先于 meta["title"]。
    """
    root = ET.Element("movie")

    def add(tag, val):
        if val is None or (isinstance(val, str) and not val.strip()):
            return
        e = ET.SubElement(root, tag)
        e.text = str(val)

    # Title policy: <title>=NUMBER+中文(或原题 fallback) / <originaltitle>=原题 / <sorttitle>=番号
    real_title = meta.get("title") or meta.get("number") or num
    base = (title_info or {}).get("display_title") or real_title
    display = compose_nfo_title(num, base)
    add("title", display)
    add("originaltitle", real_title)
    add("sorttitle", num)
    if meta.get("score"):
        add("rating", meta["score"])
    release = meta.get("release") or meta.get("publish_date")
    add("year", (release or "")[:4] if release else None)
    add("premiered", release)
    if plot:
        add("plot", plot)
        add("outline", plot)
    if meta.get("runtime"):
        add("runtime", meta["runtime"])
    studio = meta.get("producer") or meta.get("publisher")
    if studio:
        add("studio", studio)
    if meta.get("director"):
        add("director", meta["director"])
    for i, name in enumerate(parse_list(meta.get("actresses") or meta.get("actress"))):
        ae = ET.SubElement(root, "actor")
        ET.SubElement(ae, "name").text = name
        ET.SubElement(ae, "role").text = "Actress"
        ET.SubElement(ae, "order").text = str(i)
        if thumb_map and name in thumb_map:
            ET.SubElement(ae, "thumb").text = thumb_map[name]
    for g_ in parse_list(meta.get("genres") or meta.get("genre")):
        add("genre", g_)
    for g_ in parse_list(meta.get("genres") or meta.get("genre")):
        add("tag", g_)
    u1 = ET.SubElement(root, "uniqueid")
    u1.set("type", "num")
    u1.set("default", "true")
    u1.text = num
    if meta.get("cid"):
        u2 = ET.SubElement(root, "uniqueid")
        u2.set("type", "cid")
        u2.text = str(meta["cid"])
    if meta.get("trailer"):
        add("trailer", meta["trailer"])
    ET.indent(root, space="    ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
