"""统一配置：PROJECT_ROOT 动态推导 + .env + 可选 config/config.toml。

优先级：真实环境变量 > .env > 内置默认。
PROJECT_ROOT 由本文件位置动态推导（src/subsync/settings.py），
包可安装/移动到任意位置、从任意工作目录运行。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv_file() -> None:
    env_file = PROJECT_ROOT / ".env"
    if not env_file.is_file():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file)
    except Exception:
        # python-dotenv 缺失时的兜底解析（KEY=VALUE，忽略注释/空行）
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


@dataclass
class Settings:
    webdav_url: str | None
    webdav_root: str
    webdav_username: str | None
    webdav_password: str | None
    http_proxy: str | None
    https_proxy: str | None
    preferred_languages: list

    @property
    def data_dir(self) -> Path:
        return PROJECT_ROOT / "data"

    @property
    def inventory_path(self) -> Path:
        return self.data_dir / "inventory" / "inventory.json"

    @property
    def deep_search_dir(self) -> Path:
        return self.data_dir / "deep_search"

    @property
    def manifest_dir(self) -> Path:
        return self.data_dir / "manifest"

    @property
    def subtitle_cache(self) -> Path:
        return self.data_dir / "subtitle_cache"

    @property
    def configured(self) -> bool:
        """WebDAV 端点与凭据是否齐备（doctor / 命令前置检查用）。"""
        return bool(self.webdav_url and self.webdav_username and
                    self.webdav_password is not None)


def load_settings() -> Settings:
    _load_dotenv_file()
    pref = os.environ.get("SUBSYNC_PREFERRED_LANGUAGES", "zh-CN,zh-TW")
    return Settings(
        webdav_url=(os.environ.get("WEBDAV_URL") or "").rstrip("/") or None,
        webdav_root=os.environ.get("WEBDAV_ROOT", "/") or "/",
        webdav_username=os.environ.get("WEBDAV_USERNAME"),
        webdav_password=os.environ.get("WEBDAV_PASSWORD"),
        http_proxy=os.environ.get("HTTP_PROXY") or None,
        https_proxy=os.environ.get("HTTPS_PROXY") or None,
        preferred_languages=[x.strip() for x in pref.split(",") if x.strip()],
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reset_settings() -> None:
    global _settings
    _settings = None
