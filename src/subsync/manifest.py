"""字幕写回 manifest（key = 视频 remote path）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_manifest(path: Path) -> dict[str, Any]:
    if Path(path).is_file():
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return {"videos": {}}


def save_manifest(m: dict[str, Any], path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
