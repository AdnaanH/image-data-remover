"""Image metadata stripping primitives."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Literal

from PIL import Image

OutputFormat = Literal["match", "jpeg", "png"]

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"}
MIME_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}


@dataclass
class StripResult:
    ok: bool
    message: str
    verify_note: str | None = None
    input_bytes: int | None = None
    output_bytes: int | None = None
    metadata_remaining: bool | None = None


def has_meaningful_alpha(img: Image.Image) -> bool:
    if img.mode in ("RGBA", "LA", "PA"):
        return True
    if img.mode == "P" and "transparency" in img.info:
        return True
    if img.mode == "P":
        rgba = img.convert("RGBA")
        lo, _ = rgba.split()[3].getextrema()
        return lo < 255
    return False


def strip_metadata_advanced(
    input_path: str,
    output_path: str,
    *,
    quiet: bool = False,
    preserve_alpha: bool = False,
    output_format: OutputFormat = "match",
    jpeg_quality: int = 95,
) -> StripResult:
    """Strip EXIF/IPTC/XMP/ICC-like metadata by re-encoding only the pixel data."""
    try:
        input_bytes = os.path.getsize(input_path)
    except OSError:
        input_bytes = None

    try:
        with Image.open(input_path) as source:
            source.load()

            if output_format == "jpeg" and preserve_alpha and has_meaningful_alpha(source):
                if not quiet:
                    print("Note: JPEG cannot store alpha; flattening to RGB.")
                preserve_alpha = False

            work = _prepare_rgba_or_rgb(source, preserve_alpha)
            clean = Image.frombytes(work.mode, work.size, work.tobytes())

            target = _normalized_output_path(Path(output_path), output_format)
            pil_format = _pil_format_for_suffix(target.suffix.lower())
            clean.save(str(target), **_save_options(pil_format, jpeg_quality))

        with Image.open(target) as verify_img:
            verify_img.load()
            has_metadata = bool(verify_img.info)
            status = "OK (no Pillow info dict)" if not has_metadata else "WARN (Pillow info dict non-empty)"

        output_bytes = os.path.getsize(target)
        if not quiet:
            in_size = f"{input_bytes} B" if input_bytes is not None else "?"
            print(f"OK Metadata removed: {target} ({status}) -- {in_size} -> {output_bytes} B")

        return StripResult(True, "ok", status, input_bytes, output_bytes, has_metadata)
    except Exception as exc:
        if not quiet:
            print(f"FAIL Error processing {input_path}: {exc}")
        return StripResult(False, str(exc), None, input_bytes, None, None)


def _prepare_rgba_or_rgb(img: Image.Image, preserve_alpha: bool) -> Image.Image:
    if not preserve_alpha:
        return _flatten_to_rgb(img)
    if has_meaningful_alpha(img):
        if img.mode in ("P", "LA", "PA"):
            return img.convert("RGBA")
        if img.mode == "RGBA":
            return img
        return img.convert("RGBA")
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def _flatten_to_rgb(img: Image.Image) -> Image.Image:
    if img.mode == "P":
        img = img.convert("RGBA")
    if img.mode in ("LA", "PA"):
        img = img.convert("RGBA")
    if img.mode == "RGBA":
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[3])
        return background
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def _normalized_output_path(path: Path, output_format: OutputFormat) -> Path:
    if output_format == "jpeg":
        return path.with_suffix(".jpg")
    if output_format == "png":
        return path.with_suffix(".png")
    if path.suffix:
        return path.with_suffix(path.suffix.lower())
    return path.with_suffix(".png")


def _pil_format_for_suffix(suffix: str) -> str:
    if suffix in (".jpg", ".jpeg"):
        return "JPEG"
    if suffix == ".png":
        return "PNG"
    if suffix == ".webp":
        return "WEBP"
    if suffix == ".gif":
        return "GIF"
    if suffix in (".tif", ".tiff"):
        return "TIFF"
    if suffix == ".bmp":
        return "BMP"
    return "PNG"


def _save_options(pil_format: str, jpeg_quality: int) -> dict:
    quality = max(1, min(100, int(jpeg_quality)))
    opts: dict = {"format": pil_format, "exif": b"", "save_all": False}
    if pil_format == "JPEG":
        opts["quality"] = quality
        opts["optimize"] = True
    elif pil_format == "PNG":
        opts["optimize"] = True
        opts["compress_level"] = 6
    elif pil_format == "WEBP":
        opts["quality"] = max(70, quality)
        opts["method"] = 4
    elif pil_format == "GIF":
        opts["optimize"] = True
    return opts
