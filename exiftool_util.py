"""Optional ExifTool post-check (binary on PATH or EXIFTOOL_PATH)."""

from __future__ import annotations

import json
import logging
import subprocess

import settings

log = logging.getLogger(__name__)

MAX_SUMMARY_LEN = 900


def exiftool_sensitive_tag_count(path: str) -> str | None:
    """
    Returns a short ASCII summary, e.g. 'exiftool:0 EXIF/XMP/IPTC fields' or None if skipped/failed.
    """
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
            return "exiftool_error:" + tail.replace("\n", " ").replace("\r", " ")[:400]

        data = json.loads(proc.stdout or "[]")
        if not data or not isinstance(data[0], dict):
            return "exiftool:0 fields"
        obj = data[0]
        keys = []
        for k in obj:
            if k in ("SourceFile", "Error", "ExifTool"):
                continue
            head = k.split(":", 1)[0] if ":" in k else k
            if head in ("EXIF", "XMP", "IPTC", "MakerNotes", "ICC_Profile", "JFIF"):
                keys.append(k)
        s = f"exiftool:{len(keys)} EXIF/XMP/IPTC fields"
        return s[:MAX_SUMMARY_LEN]
    except subprocess.TimeoutExpired:
        log.warning("exiftool timeout for %s", path)
        return "exiftool_error:timeout"
    except Exception as e:
        log.warning("exiftool failed: %s", e)
        return "exiftool_error:" + str(e).replace("\n", " ")[:200]


def header_safe_exiftool(summary: str | None) -> str:
    if not summary:
        return ""
    return summary.replace("\r", " ").replace("\n", " ")[:MAX_SUMMARY_LEN]
