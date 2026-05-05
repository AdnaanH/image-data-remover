"""Environment-driven settings for the API server."""

from __future__ import annotations

import importlib.util
import os
import shutil
from pathlib import Path

READ_CHUNK = 1024 * 1024

API_KEY = (os.environ.get("API_KEY") or "").strip()

STRIP_MAX_MB = max(1, int(float(os.environ.get("STRIP_MAX_MB", "25"))))
MAX_UPLOAD_BYTES = STRIP_MAX_MB * 1024 * 1024

STRIP_MAX_ZIP_TOTAL_MB = max(5, int(float(os.environ.get("STRIP_MAX_ZIP_TOTAL_MB", "100"))))
MAX_ZIP_TOTAL_BYTES = STRIP_MAX_ZIP_TOTAL_MB * 1024 * 1024

MAX_BATCH_FILES = max(1, min(200, int(os.environ.get("STRIP_MAX_BATCH_FILES", "40"))))

DEFAULT_HOST = os.environ.get("STRIP_HOST", "127.0.0.1")
# Cloud hosts (Render, Railway, Fly, etc.) set PORT; STRIP_PORT overrides locally.
_default_port = os.environ.get("STRIP_PORT") or os.environ.get("PORT") or "8765"
DEFAULT_PORT = int(_default_port)

EXIFTOOL_PATH = (os.environ.get("EXIFTOOL_PATH") or "").strip()


def exiftool_binary() -> str | None:
    if EXIFTOOL_PATH and Path(EXIFTOOL_PATH).is_file():
        return EXIFTOOL_PATH
    return shutil.which("exiftool")


def rembg_available() -> bool:
    return importlib.util.find_spec("rembg") is not None
