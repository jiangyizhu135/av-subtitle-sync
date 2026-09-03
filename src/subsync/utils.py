"""Logging / output helpers: secret redaction.

Nothing that flows through user-visible output may contain credentials.
`redact_secrets()` scrubs userinfo in URLs and common header shapes.
"""
from __future__ import annotations

import re

# http(s)://user:password@host  →  http(s)://***:***@host
_URL_USERINFO_RE = re.compile(r"(?P<scheme>https?://)(?P<user>[^:/@\s]+):(?P<pw>[^@\s]+)@")
# Authorization: Bearer xxx / Basic xxx
_BEARER_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._\-]+")
_KEYVAL_RE = re.compile(
    r"(?i)\b(\w*?(?:password|passwd|secret|token|api[_-]?key|apikey|authorization|cookie))"
    r"(\s*[:=]\s*)(\S+)")


def redact_secrets(text: str) -> str:
    if not text:
        return text
    t = _URL_USERINFO_RE.sub(r"\g<scheme>***:***@", text)
    t = _BEARER_RE.sub(lambda m: f"{m.group(1)} ***", t)
    t = _KEYVAL_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}***", t)
    return t
