"""Background removal via rembg. Kept optional because it is a heavy dependency."""

from __future__ import annotations


def remove_background_png(image_bytes: bytes) -> tuple[bytes | None, str | None]:
    """Return PNG bytes plus an optional error message."""
    try:
        from rembg import remove
    except ImportError:
        return None, "Background removal is not installed on this server."

    try:
        out = remove(image_bytes)
        if not out:
            return None, "Background removal returned an empty output."
        return out, None
    except Exception as exc:
        return None, f"Background removal failed: {exc}"
