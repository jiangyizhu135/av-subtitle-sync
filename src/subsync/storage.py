"""WebDAV Storage backend —— 跨平台、provider 无关。

行为说明（来自真实 WebDAV 服务器的兼容性经验，保留为默认策略）：
  - PROPFIND（requests，本机 http 源站）返回 207，href 为 percent-encoded UTF-8
  - 文件 GET 优先走 curl 子进程：部分签名 CDN 会拒绝 Python/urllib 的 TLS 指纹
    （表现为 403 / SSL EOF），curl 稳定
  - 中文路径：逻辑路径保持 UTF-8，URL 编码交给 curl/requests，不做手工双重编码
  - 远端路径语义是 POSIX：内部一律用 str + "/"，不与本地 pathlib 混用
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit


@dataclass
class DavEntry:
    rel: str            # 相对 dav 根（即媒体根）的 posix 路径，已解码
    is_dir: bool
    size: int | None


class WebDAVStorage:
    def __init__(self, base_url: str, username: str, password: str) -> None:
        self.base = base_url.rstrip("/")
        self.username = username
        self.password = password
        self._base_path = urlsplit(self.base).path  # 如 "/dav"

    # ---- URL / path ----
    def url_for(self, rel: str) -> str:
        """rel（媒体根相对路径）→ dav URL。中文由 curl/requests 负责编码。"""
        rel = rel.lstrip("/")
        if not rel:
            return self.base + "/"
        return f"{self.base}/{rel}"

    def _strip_base(self, href_path: str) -> str:
        p = href_path
        if self._base_path and p.startswith(self._base_path):
            p = p[len(self._base_path):]
        return p.strip("/")

    def _session(self):
        import requests
        s = requests.Session()
        s.auth = (self.username, self.password)
        s.headers["User-Agent"] = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                   "AppleWebKit/537.36 Chrome/120 Safari/537.36")
        return s

    # ---- PROPFIND ----
    def propfind(self, rel_dir: str = "", depth: str = "1", timeout: int = 60):
        """返回 (status, [DavEntry])。status 非 207 时 entries 为空。"""
        s = self._session()
        try:
            r = s.request("PROPFIND", self.url_for(rel_dir), headers={"Depth": depth}, timeout=timeout)
        except Exception as e:
            return 0, [], f"NETWORK_ERROR:{type(e).__name__}"
        if r.status_code != 207:
            return r.status_code, [], None
        from lxml import etree
        try:
            root = etree.fromstring(r.content)
        except Exception as e:
            return r.status_code, [], f"XML_PARSE_ERROR:{e}"
        entries = []
        for resp in root.findall(".//{DAV:}response"):
            href_el = resp.find("{DAV:}href")
            if href_el is None or not (href_el.text or "").strip():
                continue
            href = unquote(urlsplit(href_el.text).path)
            rel = self._strip_base(href)
            prop = resp.find(".//{DAV:}prop")
            is_dir = prop is not None and prop.find("{DAV:}resourcetype/{DAV:}collection") is not None
            size = None
            if prop is not None:
                len_el = prop.find("{DAV:}getcontentlength")
                if len_el is not None and (len_el.text or "").strip().isdigit():
                    size = int(len_el.text)
            entries.append(DavEntry(rel=rel, is_dir=is_dir, size=size))
        return r.status_code, entries, None

    def walk(self, rel_dir: str = "") -> list[DavEntry]:
        """递归枚举全部文件。优先 Depth:infinity；不可用退回递归 Depth:1。"""
        status, entries, _err = self.propfind(rel_dir, "infinity")
        if status == 207 and entries:
            return [e for e in entries if not e.is_dir]
        files: list[DavEntry] = []
        seen: set[str] = set()

        def walk1(d: str):
            status, entries, _ = self.propfind(d, "1")
            if status != 207:
                return
            for e in entries:
                if e.rel in seen or e.rel == d:
                    continue
                seen.add(e.rel)
                if e.is_dir:
                    walk1(e.rel)
                else:
                    files.append(e)

        walk1(rel_dir)
        return files

    # ---- GET ----
    def get(self, rel: str) -> bytes | None:
        url = self.url_for(rel)
        try:
            r = subprocess.run(
                [shutil.which("curl") or "curl", "-sg",
                 "-u", f"{self.username}:{self.password}",
                 "-L", "--max-time", "40", url],
                capture_output=True, timeout=60)
            if r.returncode == 0 and r.stdout:
                return r.stdout
        except Exception:
            pass
        return None

    # ---- PUT（本阶段禁止用于字幕；仅为后续审批流程保留接口） ----
    def put(self, rel: str, data: bytes, ctype: str = "application/octet-stream") -> int:
        url = self.url_for(rel)
        try:
            s = self._session()
            r = s.put(url, data=data, timeout=90, allow_redirects=True,
                      headers={"Content-Type": ctype})
            return r.status_code
        except Exception as e:
            return getattr(e, "status_code", None) or 0
