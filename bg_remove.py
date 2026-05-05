"""Background removal via rembg (U^2-Net). Optional heavy dependency."""

from __future__ import annotations


def remove_background_png(image_bytes: bytes) -> tuple[bytes | None, str | None]:
    """
    Returns (png_bytes, error_message). On success error_message is None.
    """
    try:
        from rembg import remove
    except ImportError:
        return None, "rembg is not installed. Run: pip install rembg onnxruntime"

    try:
        out = remove(image_bytes)
        if not out:
            return None, "rembg returned empty output"
        return out, None
    except Exception as e:
        return None, f"rembg failed: {e}"
