"""HTTP backend abstraction.

Subtitle sites and WebDAV endpoints behave differently across HTTP stacks:
some CDNs reject non-curl TLS fingerprints (SSL EOF on Python, 200 on curl),
while plain Python `requests` works fine elsewhere and is easier to deploy.

Two backends are provided; adapters choose per source:

  - CurlHTTPBackend   subprocess `curl` (discovered via shutil.which, never a
                      hard-coded /usr/bin path); argument-list invocation only.
  - PythonHTTPBackend portable `requests`.

`auto` prefers curl when available and falls back to Python.
"""
from __future__ import annotations

import shutil
import subprocess

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "Chrome/120 Safari/537.36")


class CurlUnavailable(RuntimeError):
    """curl executable not found on PATH."""


def curl_path() -> str | None:
    """Locate curl (curl.exe on Windows). Never hard-codes a system path."""
    return shutil.which("curl")


def _run_curl(url: str, timeout: int, extra: list[str]) -> tuple[int, bytes]:
    exe = curl_path()
    if not exe:
        raise CurlUnavailable("CURL_NOT_AVAILABLE: curl not found on PATH")
    cmd = [exe, "-sg", "-L", "--max-time", str(timeout), "-A", UA,
           "-w", "\n%{http_code}", *extra, url]
    r = subprocess.run(cmd, capture_output=True, timeout=timeout + 15)
    if r.returncode != 0:
        return 0, b""
    body, _, code = r.stdout.rpartition(b"\n")
    try:
        return int(code.strip()), body
    except ValueError:
        return 0, b""


class CurlHTTPBackend:
    name = "curl"

    def get(self, url: str, timeout: int = 40, retries: int = 3,
            retry_delay: float = 1.0) -> tuple[int, bytes]:
        """GET with bounded retries for transient failures (TLS EOF etc.)."""
        import time
        last = (0, b"")
        for attempt in range(retries):
            try:
                last = _run_curl(url, timeout, [])
            except Exception:
                last = (0, b"")
            if last[0] == 200:
                return last
            time.sleep(retry_delay * (1 + attempt))
        return last


class PythonHTTPBackend:
    name = "python"

    def __init__(self, proxies: dict | None = None):
        self.proxies = proxies

    def get(self, url: str, timeout: int = 40, retries: int = 3,
            retry_delay: float = 1.0) -> tuple[int, bytes]:
        import time

        import requests
        last = (0, b"")
        for attempt in range(retries):
            try:
                r = requests.get(url, timeout=timeout, proxies=self.proxies,
                                 headers={"User-Agent": UA})
                if r.status_code == 200 and r.content:
                    return 200, r.content
                last = (r.status_code, r.content[:0])
            except Exception:
                last = (0, b"")
            time.sleep(retry_delay * (1 + attempt))
        return last


def get_backend(mode: str = "auto", proxies: dict | None = None):
    """mode: 'curl' | 'python' | 'auto'. auto = curl if installed else python."""
    if mode == "curl":
        return CurlHTTPBackend()
    if mode == "python":
        return PythonHTTPBackend(proxies)
    if curl_path():
        return CurlHTTPBackend()
    return PythonHTTPBackend(proxies)
