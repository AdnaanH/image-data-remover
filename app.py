from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image

OutputFormat = Literal["match", "jpeg", "png"]


@dataclass
class StripResult:
    ok: bool
    message: str
    verify_note: str | None = None
    input_bytes: int | None = None
    output_bytes: int | None = None
    metadata_remaining: bool | None = None


def _has_meaningful_alpha(img: Image.Image) -> bool:
    if img.mode in ("RGBA", "LA", "PA"):
        return True
    if img.mode == "P" and "transparency" in img.info:
        return True
    if img.mode == "P":
        rgba = img.convert("RGBA")
        a = rgba.split()[3]
        lo, hi = a.getextrema()
        return lo < 255
    return False


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


def _prepare_rgba_or_rgb(img: Image.Image, preserve_alpha: bool) -> Image.Image:
    if not preserve_alpha:
        return _flatten_to_rgb(img)
    if _has_meaningful_alpha(img):
        if img.mode == "P":
            return img.convert("RGBA")
        if img.mode in ("LA", "PA"):
            return img.convert("RGBA")
        if img.mode == "RGBA":
            return img
        return img.convert("RGBA")
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def _pil_format_for_suffix(suffix: str) -> str:
    s = suffix.lower()
    if s in (".jpg", ".jpeg"):
        return "JPEG"
    if s == ".png":
        return "PNG"
    if s == ".webp":
        return "WEBP"
    if s == ".gif":
        return "GIF"
    if s in (".tif", ".tiff"):
        return "TIFF"
    if s == ".bmp":
        return "BMP"
    return "PNG"


def _save_options(pil_format: str, jpeg_quality: int) -> dict:
    q = max(1, min(100, int(jpeg_quality)))
    opts: dict = {"format": pil_format, "exif": b"", "save_all": False}
    if pil_format == "JPEG":
        opts["quality"] = q
        opts["optimize"] = True
    elif pil_format == "PNG":
        opts["optimize"] = True
        opts["compress_level"] = 6
    elif pil_format == "WEBP":
        opts["quality"] = max(70, q)
        opts["method"] = 4
    elif pil_format == "GIF":
        opts["optimize"] = True
    elif pil_format == "BMP":
        pass
    elif pil_format == "TIFF":
        pass
    return opts


def strip_metadata_advanced(
    input_path: str,
    output_path: str,
    *,
    quiet: bool = False,
    preserve_alpha: bool = False,
    output_format: OutputFormat = "match",
    jpeg_quality: int = 95,
) -> StripResult:
    """
    Strip metadata (EXIF, IPTC, XMP, ICC, etc.) by re-encoding pixels into a new image.

    preserve_alpha: keep transparency when saving as PNG/WebP (JPEG always flattens).
    output_format: match uses output_path's extension; jpeg/png force container and suffix.
    """
    try:
        input_bytes = os.path.getsize(input_path)
    except OSError:
        input_bytes = None

    try:
        with Image.open(input_path) as src:
            src.load()

            if output_format == "jpeg" and preserve_alpha and _has_meaningful_alpha(src):
                if not quiet:
                    print("Note: JPEG cannot store alpha; flattening to RGB.")
                preserve_alpha = False

            work = _prepare_rgba_or_rgb(src, preserve_alpha)
            raw = work.tobytes()
            clean = Image.frombytes(work.mode, work.size, raw)

            p = Path(output_path)
            if output_format == "jpeg":
                p = p.with_suffix(".jpg")
            elif output_format == "png":
                p = p.with_suffix(".png")
            elif p.suffix:
                p = p.with_suffix(p.suffix.lower())
            else:
                p = p.with_suffix(".png")
            output_path = str(p)
            pil_fmt = _pil_format_for_suffix(p.suffix.lower())

            save_kw = _save_options(pil_fmt, jpeg_quality)
            clean.save(output_path, **save_kw)

        with Image.open(output_path) as verify_img:
            verify_img.load()
            has_metadata = bool(verify_img.info)
            status = "OK (no Pillow info dict)" if not has_metadata else "WARN (Pillow info dict non-empty)"

        out_size = os.path.getsize(output_path)

        if not quiet:
            in_h = f"{input_bytes} B" if input_bytes is not None else "?"
            print(f"OK Metadata removed: {output_path} ({status}) -- {in_h} -> {out_size} B")
        return StripResult(
            True,
            "ok",
            status,
            input_bytes,
            out_size,
            metadata_remaining=has_metadata,
        )

    except Exception as e:
        msg = f"Error processing {input_path}: {str(e)}"
        if not quiet:
            print(f"FAIL {msg}")
        return StripResult(False, str(e), None, input_bytes, None, None)


def main():
    parser = argparse.ArgumentParser(
        description="Strip metadata from images (AI-generated or any image)",
    )
    parser.add_argument(
        "input",
        help="Input image file path",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output file path (default: same name with _clean suffix)",
        default=None,
    )
    parser.add_argument(
        "-d",
        "--directory",
        help="Process all images in a directory",
        action="store_true",
    )
    parser.add_argument(
        "--preserve-alpha",
        action="store_true",
        help="Keep transparency (PNG/WebP/BMP/TIFF); JPEG still flattens",
    )
    parser.add_argument(
        "--format",
        choices=("match", "jpeg", "png"),
        default="match",
        help="Output container: match extension, force JPEG, or force PNG",
    )
    parser.add_argument(
        "-q",
        "--quality",
        type=int,
        default=95,
        metavar="1-100",
        help="JPEG/WebP quality (default 95)",
    )

    args = parser.parse_args()
    out_fmt: OutputFormat = args.format  # type: ignore[assignment]

    if args.directory:
        input_dir = Path(args.input)
        if not input_dir.is_dir():
            print(f"FAIL Directory not found: {args.input}")
            return

        image_extensions = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif")
        images = [f for f in input_dir.iterdir() if f.suffix.lower() in image_extensions]

        if not images:
            print(f"FAIL No images found in {args.input}")
            return

        success_count = 0
        for img_file in images:
            stem = img_file.stem
            if args.format == "jpeg":
                out = img_file.parent / f"{stem}_clean.jpg"
            elif args.format == "png":
                out = img_file.parent / f"{stem}_clean.png"
            else:
                out = img_file.parent / f"{stem}_clean{img_file.suffix}"
            if strip_metadata_advanced(
                str(img_file),
                str(out),
                preserve_alpha=args.preserve_alpha,
                output_format=out_fmt,
                jpeg_quality=args.quality,
            ).ok:
                success_count += 1

        print(f"\nOK Processed {success_count}/{len(images)} images")
    else:
        if not os.path.exists(args.input):
            print(f"FAIL File not found: {args.input}")
            return

        if args.output is None:
            base, ext = os.path.splitext(args.input)
            if args.format == "jpeg":
                ext = ".jpg"
            elif args.format == "png":
                ext = ".png"
            args.output = f"{base}_clean{ext}"
        else:
            outp = Path(args.output)
            if args.format == "jpeg":
                args.output = str(outp.with_suffix(".jpg"))
            elif args.format == "png":
                args.output = str(outp.with_suffix(".png"))

        strip_metadata_advanced(
            args.input,
            args.output,
            preserve_alpha=args.preserve_alpha,
            output_format=out_fmt,
            jpeg_quality=args.quality,
        )


if __name__ == "__main__":
    main()
