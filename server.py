"""
Local FastAPI server: metadata strip, batch ZIP, optional ExifTool check, rembg, optional API key.
Run: python server.py
"""

from __future__ import annotations

import json
import logging
import tempfile
import zipfile
from pathlib import Path
from typing import Annotated, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import OutputFormat, strip_metadata_advanced
from auth_deps import require_api_key_if_configured
import bg_remove
import exiftool_util
import settings

log = logging.getLogger(__name__)

ALLOWED = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"}

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

app = FastAPI(title="Image metadata remover", version="2.0.0")
app.mount("/static", StaticFiles(directory="static"), name="static")


def _unlink_path(path: str) -> None:
    Path(path).unlink(missing_ok=True)


def _safe_name(name: str | None) -> str:
    if not name:
        return "image.bin"
    base = Path(name).name
    if not base or base in (".", ".."):
        return "image.bin"
    return base


async def _read_upload_limited(upload: UploadFile) -> bytes:
    total = 0
    parts: list[bytes] = []
    while True:
        chunk = await upload.read(settings.READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > settings.MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"File too large (max {settings.STRIP_MAX_MB} MB per file)",
            )
        parts.append(chunk)
    return b"".join(parts)


def _maybe_exiftool(path: str, requested: bool) -> str | None:
    if not requested:
        return None
    exe = settings.exiftool_binary()
    if not exe:
        return "skipped_no_exiftool_binary"
    return exiftool_util.exiftool_sensitive_tag_count(path)


@app.get("/", response_class=HTMLResponse)
def root():
    index = Path(__file__).resolve().parent / "static" / "index.html"
    try:
        return index.read_text(encoding="utf-8")
    except FileNotFoundError:
        log.error("UI missing: %s (create static/index.html beside server.py)", index)
        raise HTTPException(
            status_code=503,
            detail=f"UI not found at {index}. Restore static/index.html in the project folder.",
        ) from None
    except UnicodeDecodeError as e:
        log.error("UI encoding error: %s", e)
        raise HTTPException(
            status_code=503,
            detail="static/index.html must be valid UTF-8.",
        ) from e


@app.get("/health")
def health():
    return {
        "ok": True,
        "version": app.version,
        "max_upload_mb": settings.STRIP_MAX_MB,
        "max_zip_total_mb": settings.STRIP_MAX_ZIP_TOTAL_MB,
        "max_batch_files": settings.MAX_BATCH_FILES,
        "auth_required": bool(settings.API_KEY),
        "rembg": settings.rembg_available(),
        "exiftool": settings.exiftool_binary() is not None,
    }


@app.post("/api/strip", dependencies=[Depends(require_api_key_if_configured)])
async def api_strip(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    preserve_alpha: bool = Query(False),
    output: Literal["match", "jpeg", "png"] = Query("match"),
    quality: int = Query(95, ge=1, le=100),
    exiftool_check: bool = Query(False, description="Run ExifTool on output if available"),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported type {suffix or '(none)'}. Allowed: {', '.join(sorted(ALLOWED))}",
        )

    tmp_in: str | None = None
    tmp_out: str | None = None
    try:
        content = await _read_upload_limited(file)
        if not content:
            raise HTTPException(status_code=400, detail="Empty file")

        out_fmt: OutputFormat = output  # type: ignore[assignment]
        if out_fmt == "jpeg":
            out_suffix = ".jpg"
        elif out_fmt == "png":
            out_suffix = ".png"
        else:
            out_suffix = suffix

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f_in:
            tmp_in = f_in.name
            f_in.write(content)

        with tempfile.NamedTemporaryFile(delete=False, suffix=out_suffix) as f_out:
            tmp_out = f_out.name

        result = strip_metadata_advanced(
            tmp_in,
            tmp_out,
            quiet=True,
            preserve_alpha=preserve_alpha,
            output_format=out_fmt,
            jpeg_quality=quality,
        )
        if not result.ok:
            raise HTTPException(status_code=422, detail=result.message)

        p_out = Path(tmp_out)
        out_name = f"{Path(file.filename).stem}_clean{p_out.suffix.lower()}"
        media = MIME_BY_SUFFIX.get(p_out.suffix.lower(), "application/octet-stream")

        extra_headers: dict[str, str] = {}
        if result.input_bytes is not None:
            extra_headers["X-Input-Bytes"] = str(result.input_bytes)
        if result.output_bytes is not None:
            extra_headers["X-Output-Bytes"] = str(result.output_bytes)
        if result.metadata_remaining is not None:
            extra_headers["X-Metadata-Remaining"] = "true" if result.metadata_remaining else "false"

        exif_summary = _maybe_exiftool(tmp_out, exiftool_check)
        if exiftool_check:
            extra_headers["X-Exiftool-Summary"] = exiftool_util.header_safe_exiftool(
                exif_summary or "skipped"
            )

        if tmp_in:
            _unlink_path(tmp_in)
            tmp_in = None

        background_tasks.add_task(_unlink_path, tmp_out)

        return FileResponse(
            tmp_out,
            filename=out_name,
            media_type=media,
            headers=extra_headers,
        )
    except HTTPException:
        if tmp_in:
            _unlink_path(tmp_in)
        if tmp_out:
            _unlink_path(tmp_out)
        raise
    except Exception as e:
        log.exception("strip failed")
        if tmp_in:
            _unlink_path(tmp_in)
        if tmp_out:
            _unlink_path(tmp_out)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/strip-zip", dependencies=[Depends(require_api_key_if_configured)])
async def api_strip_zip(
    background_tasks: BackgroundTasks,
    files: Annotated[list[UploadFile], File(description="One or more images")],
    preserve_alpha: bool = Query(False),
    output: Literal["match", "jpeg", "png"] = Query("match"),
    quality: int = Query(95, ge=1, le=100),
    exiftool_check: bool = Query(False),
):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    if len(files) > settings.MAX_BATCH_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files (max {settings.MAX_BATCH_FILES})",
        )

    payloads: list[tuple[str, bytes]] = []
    total = 0
    for f in files:
        raw = await _read_upload_limited(f)
        if not raw:
            continue
        total += len(raw)
        if total > settings.MAX_ZIP_TOTAL_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Total upload too large (max {settings.STRIP_MAX_ZIP_TOTAL_MB} MB for ZIP batch)",
            )
        payloads.append((_safe_name(f.filename), raw))

    if not payloads:
        raise HTTPException(status_code=400, detail="All files were empty")

    zip_path: str | None = None
    try:
        manifest: dict = {"version": 1, "files": []}

        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as zf:
            zip_path = zf.name

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for safe_fn, content in payloads:
                suffix = Path(safe_fn).suffix.lower() or ".png"
                if suffix not in ALLOWED:
                    manifest["files"].append(
                        {"original": safe_fn, "error": f"unsupported extension {suffix}"}
                    )
                    continue

                out_fmt: OutputFormat = output  # type: ignore[assignment]
                if out_fmt == "jpeg":
                    out_suffix = ".jpg"
                elif out_fmt == "png":
                    out_suffix = ".png"
                else:
                    out_suffix = suffix

                tin: str | None = None
                tout: str | None = None
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f_in:
                        tin = f_in.name
                        f_in.write(content)

                    with tempfile.NamedTemporaryFile(delete=False, suffix=out_suffix) as f_out:
                        tout = f_out.name

                    result = strip_metadata_advanced(
                        tin,
                        tout,
                        quiet=True,
                        preserve_alpha=preserve_alpha,
                        output_format=out_fmt,
                        jpeg_quality=quality,
                    )
                    if tin:
                        _unlink_path(tin)
                        tin = None

                    if not result.ok:
                        manifest["files"].append({"original": safe_fn, "error": result.message})
                        continue

                    stem = Path(safe_fn).stem
                    arcname = f"{stem}_clean{Path(tout).suffix.lower()}"
                    zout.write(tout, arcname=arcname)

                    exif_summary = _maybe_exiftool(tout, exiftool_check)
                    entry = {
                        "original": safe_fn,
                        "zip_path": arcname,
                        "input_bytes": result.input_bytes,
                        "output_bytes": result.output_bytes,
                        "metadata_remaining": result.metadata_remaining,
                    }
                    if exiftool_check:
                        entry["exiftool"] = exif_summary
                    manifest["files"].append(entry)
                finally:
                    if tin:
                        _unlink_path(tin)
                    if tout:
                        _unlink_path(tout)

            zout.writestr("manifest.json", json.dumps(manifest, indent=2))

        background_tasks.add_task(_unlink_path, zip_path)

        return FileResponse(
            zip_path,
            filename="stripped_images.zip",
            media_type="application/zip",
        )
    except HTTPException:
        if zip_path:
            _unlink_path(zip_path)
        raise
    except Exception as e:
        log.exception("strip-zip failed")
        if zip_path:
            _unlink_path(zip_path)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/remove-bg", dependencies=[Depends(require_api_key_if_configured)])
async def api_remove_bg(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    strip_metadata: bool = Query(True, description="Re-encode output to strip metadata while keeping alpha"),
    exiftool_check: bool = Query(False),
):
    if not settings.rembg_available():
        raise HTTPException(
            status_code=501,
            detail="rembg is not installed on the server. pip install rembg onnxruntime",
        )

    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(status_code=400, detail=f"Unsupported type {suffix}")

    tmp_raw: str | None = None
    tmp_out: str | None = None
    try:
        content = await _read_upload_limited(file)
        if not content:
            raise HTTPException(status_code=400, detail="Empty file")

        png_bytes, err = bg_remove.remove_background_png(content)
        if err or not png_bytes:
            raise HTTPException(status_code=422, detail=err or "rembg failed")

        stem = Path(file.filename).stem

        if not strip_metadata:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tr:
                tmp_raw = tr.name
                tr.write(png_bytes)
            tmp_out = tmp_raw
            tmp_raw = None
            out_name = f"{stem}_nobg.png"
            extra: dict[str, str] = {"X-Rembg-Stripped": "false"}
        else:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tr:
                tmp_raw = tr.name
                tr.write(png_bytes)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as fo:
                tmp_out = fo.name
            result = strip_metadata_advanced(
                tmp_raw,
                tmp_out,
                quiet=True,
                preserve_alpha=True,
                output_format="png",
                jpeg_quality=95,
            )
            if not result.ok:
                _unlink_path(tmp_raw)
                tmp_raw = None
                _unlink_path(tmp_out)
                tmp_out = None
                raise HTTPException(status_code=422, detail=result.message)
            _unlink_path(tmp_raw)
            tmp_raw = None
            out_name = f"{stem}_nobg_clean.png"
            extra = {
                "X-Rembg-Stripped": "true",
                "X-Input-Bytes": str(result.input_bytes or len(content)),
                "X-Output-Bytes": str(result.output_bytes or ""),
                "X-Metadata-Remaining": "true"
                if result.metadata_remaining
                else "false",
            }

        exif_summary = _maybe_exiftool(tmp_out, exiftool_check)
        if exiftool_check:
            extra["X-Exiftool-Summary"] = exiftool_util.header_safe_exiftool(
                exif_summary or "skipped"
            )

        background_tasks.add_task(_unlink_path, tmp_out)

        return FileResponse(
            tmp_out,
            filename=out_name,
            media_type="image/png",
            headers=extra,
        )
    except HTTPException:
        if tmp_raw:
            _unlink_path(tmp_raw)
        if tmp_out:
            _unlink_path(tmp_out)
        raise
    except Exception as e:
        log.exception("remove-bg failed")
        if tmp_raw:
            _unlink_path(tmp_raw)
        if tmp_out:
            _unlink_path(tmp_out)
        raise HTTPException(status_code=500, detail=str(e)) from e


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server:app",
        host=settings.DEFAULT_HOST,
        port=settings.DEFAULT_PORT,
        reload=True,
    )
