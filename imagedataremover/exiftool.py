"""Optional ExifTool post-processing checks."""

from __future__ import annotations

import json
import logging
import subprocess

from .config import settings

log = logging.getLogger(__name__)

MAX_SUMMARY_LEN = 900
SENSITIVE_GROUPS = {"EXIF", "XMP", "IPTC", "MakerNotes", "ICC_Profile", "JFIF"}


def sensitive_tag_count(path: str) -> str | None:
    """Return a short ASCII summary of sensitive metadata groups."""
    exe = settings.exiftool_binary()
    if not exe:
        return None

    try:
        proc = subprocess.run(
            [exe, "-json", "-n", path],
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip()[:400]
            return _header_safe("exiftool_error:" + tail)

        data = json.loads(proc.stdout or "[]")
        if not data or not isinstance(data[0], dict):
            return "exiftool:0 fields"

        keys = []
        for key in data[0]:
            if key in ("SourceFile", "Error", "ExifTool"):
                continue
            group = key.split(":", 1)[0] if ":" in key else key
            if group in SENSITIVE_GROUPS:
                keys.append(key)
        return f"exiftool:{len(keys)} EXIF/XMP/IPTC fields"[:MAX_SUMMARY_LEN]
    except subprocess.TimeoutExpired:
        log.warning("exiftool timeout for %s", path)
        return "exiftool_error:timeout"
    except Exception as exc:
        log.warning("exiftool failed: %s", exc)
        return _header_safe("exiftool_error:" + str(exc))


def header_safe(summary: str | None) -> str:
    return _header_safe(summary or "")


def _header_safe(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ")[:MAX_SUMMARY_LEN]
