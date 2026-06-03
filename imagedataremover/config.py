"""Environment-driven settings for the API server."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import os
from pathlib import Path
import shutil


def _int_env(name: str, default: int, *, minimum: int, maximum: int | None = None) -> int:
    raw = os.environ.get(name)
    try:
        value = int(float(raw)) if raw is not None else default
    except ValueError:
        value = default
    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _list_env(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    read_chunk: int = 1024 * 1024
    api_key: str = (os.environ.get("API_KEY") or "").strip()
    max_upload_mb: int = _int_env("STRIP_MAX_MB", 25, minimum=1)
    max_zip_total_mb: int = _int_env("STRIP_MAX_ZIP_TOTAL_MB", 100, minimum=5)
    max_batch_files: int = _int_env("STRIP_MAX_BATCH_FILES", 40, minimum=1, maximum=200)
    host: str = os.environ.get("STRIP_HOST", "127.0.0.1")
    port: int = _int_env("STRIP_PORT", _int_env("PORT", 8765, minimum=1), minimum=1)
    exiftool_path: str = (os.environ.get("EXIFTOOL_PATH") or "").strip()
    allowed_origins: tuple[str, ...] = tuple(_list_env("STRIP_ALLOWED_ORIGINS"))
    public_site_url: str = (os.environ.get("PUBLIC_SITE_URL") or "").strip()

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def max_zip_total_bytes(self) -> int:
        return self.max_zip_total_mb * 1024 * 1024

    def exiftool_binary(self) -> str | None:
        if self.exiftool_path and Path(self.exiftool_path).is_file():
            return self.exiftool_path
        return shutil.which("exiftool")

    def rembg_available(self) -> bool:
        return importlib.util.find_spec("rembg") is not None


settings = Settings()
