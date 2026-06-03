"""Command-line entry point for metadata stripping.

Examples:
    python app.py photo.jpg
    python app.py ./images --directory --format png --preserve-alpha
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from imagedataremover.imaging import ALLOWED_EXTENSIONS, OutputFormat, strip_metadata_advanced


def main() -> None:
    parser = argparse.ArgumentParser(description="Strip metadata from local image files.")
    parser.add_argument("input", help="Input image path, or directory when --directory is used.")
    parser.add_argument("-o", "--output", default=None, help="Output path for single-file mode.")
    parser.add_argument("-d", "--directory", action="store_true", help="Process every image in a directory.")
    parser.add_argument("--preserve-alpha", action="store_true", help="Keep transparency where the format supports it.")
    parser.add_argument(
        "--format",
        choices=("match", "jpeg", "png"),
        default="match",
        help="Output container: match input, force JPEG, or force PNG.",
    )
    parser.add_argument("-q", "--quality", type=int, default=95, metavar="1-100", help="JPEG/WebP quality.")
    args = parser.parse_args()

    output_format: OutputFormat = args.format  # type: ignore[assignment]
    if args.directory:
        _process_directory(Path(args.input), output_format, args.preserve_alpha, args.quality)
        return

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"FAIL File not found: {input_path}")
        return

    output_path = Path(args.output) if args.output else _default_output_path(input_path, output_format)
    if output_format == "jpeg":
        output_path = output_path.with_suffix(".jpg")
    elif output_format == "png":
        output_path = output_path.with_suffix(".png")

    strip_metadata_advanced(
        str(input_path),
        str(output_path),
        preserve_alpha=args.preserve_alpha,
        output_format=output_format,
        jpeg_quality=args.quality,
    )


def _process_directory(path: Path, output_format: OutputFormat, preserve_alpha: bool, quality: int) -> None:
    if not path.is_dir():
        print(f"FAIL Directory not found: {path}")
        return

    images = [item for item in path.iterdir() if item.suffix.lower() in ALLOWED_EXTENSIONS]
    if not images:
        print(f"FAIL No images found in {path}")
        return

    success_count = 0
    for image_path in images:
        output_path = _default_output_path(image_path, output_format)
        if strip_metadata_advanced(
            str(image_path),
            str(output_path),
            preserve_alpha=preserve_alpha,
            output_format=output_format,
            jpeg_quality=quality,
        ).ok:
            success_count += 1

    print(f"\nOK Processed {success_count}/{len(images)} images")


def _default_output_path(input_path: Path, output_format: OutputFormat) -> Path:
    suffix = input_path.suffix
    if output_format == "jpeg":
        suffix = ".jpg"
    elif output_format == "png":
        suffix = ".png"
    return input_path.with_name(f"{input_path.stem}_clean{suffix}")


if __name__ == "__main__":
    main()
