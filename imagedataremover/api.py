"""FastAPI application factory and routes."""

from __future__ import annotations

import json
import logging
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Annotated, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .auth import require_api_key_if_configured
from .background import remove_background_png
from .config import settings
from .exiftool import header_safe, sensitive_tag_count
from .imaging import ALLOWED_EXTENSIONS, MIME_BY_SUFFIX, OutputFormat, strip_metadata_advanced

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = PROJECT_ROOT / "static"
SAFE_STEM_RE = re.compile(r"[^A-Za-z0-9._-]+")


def create_app() -> FastAPI:
    api = FastAPI(
        title="CleanFrame API",
        summary="Strip image metadata, batch-clean files, and create metadata-safe cut-outs.",
        version=__version__,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        swagger_ui_oauth2_redirect_url="/api/docs/oauth2-redirect",
    )

    if settings.allowed_origins:
        api.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.allowed_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "X-API-Key"],
        )

    api.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @api.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Content-Security-Policy", _content_security_policy(request.url.path))
        return response

    return api


app = create_app()


@app.exception_handler(Exception)
async def internal_error_handler(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Check server logs for details."},
    )


@app.get("/", response_class=HTMLResponse)
def root():
    return _read_static_html("index.html")


@app.get("/docs", response_class=HTMLResponse)
def docs_page():
    return _read_static_html("docs.html")


@app.get("/api", include_in_schema=False)
def api_redirect():
    return RedirectResponse("/api/docs")


@app.get("/api-docs", include_in_schema=False)
def api_docs_redirect():
    return RedirectResponse("/api/docs")


@app.get("/health")
def health():
    return {
        "ok": True,
        "name": "CleanFrame",
        "version": app.version,
        "max_upload_mb": settings.max_upload_mb,
        "max_zip_total_mb": settings.max_zip_total_mb,
        "max_batch_files": settings.max_batch_files,
        "auth_required": bool(settings.api_key),
        "background_removal": settings.rembg_available(),
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
    filename, suffix = _validate_upload_name(file)
    content = await _read_upload_limited(file)
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")

    out_suffix = _output_suffix(output, suffix)
    tmp_in: str | None = None
    tmp_out: str | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as input_file:
            tmp_in = input_file.name
            input_file.write(content)

        with tempfile.NamedTemporaryFile(delete=False, suffix=out_suffix) as output_file:
            tmp_out = output_file.name

        result = strip_metadata_advanced(
            tmp_in,
            tmp_out,
            quiet=True,
            preserve_alpha=preserve_alpha,
            output_format=output,
            jpeg_quality=quality,
        )
        if not result.ok:
            raise HTTPException(status_code=422, detail=result.message)

        output_path = Path(tmp_out)
        output_name = f"{_safe_stem(filename)}_clean{output_path.suffix.lower()}"
        headers = _result_headers(result)
        exif_summary = _maybe_exiftool(tmp_out, exiftool_check)
        if exiftool_check:
            headers["X-Exiftool-Summary"] = header_safe(exif_summary or "skipped")

        _unlink_path(tmp_in)
        tmp_in = None
        background_tasks.add_task(_unlink_path, tmp_out)

        return FileResponse(
            tmp_out,
            filename=output_name,
            media_type=MIME_BY_SUFFIX.get(output_path.suffix.lower(), "application/octet-stream"),
            headers=headers,
        )
    except HTTPException:
        _cleanup(tmp_in, tmp_out)
        raise
    except Exception as exc:
        log.exception("strip failed")
        _cleanup(tmp_in, tmp_out)
        raise HTTPException(status_code=500, detail="Could not process that image.") from exc


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
        raise HTTPException(status_code=400, detail="No files uploaded.")
    if len(files) > settings.max_batch_files:
        raise HTTPException(status_code=400, detail=f"Too many files. Max: {settings.max_batch_files}.")

    payloads: list[tuple[str, str, bytes]] = []
    total = 0
    for upload in files:
        filename, suffix = _validate_upload_name(upload)
        raw = await _read_upload_limited(upload)
        if not raw:
            continue
        total += len(raw)
        if total > settings.max_zip_total_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Total upload too large. Max: {settings.max_zip_total_mb} MB.",
            )
        payloads.append((filename, suffix, raw))

    if not payloads:
        raise HTTPException(status_code=400, detail="All files were empty.")

    zip_path: str | None = None
    try:
        manifest: dict = {"app": "CleanFrame", "version": app.version, "files": []}
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as zip_file:
            zip_path = zip_file.name

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for filename, suffix, content in payloads:
                _write_clean_image_to_zip(
                    archive,
                    manifest,
                    filename,
                    suffix,
                    content,
                    output=output,
                    preserve_alpha=preserve_alpha,
                    quality=quality,
                    exiftool_check=exiftool_check,
                )
            archive.writestr("manifest.json", json.dumps(manifest, indent=2))

        background_tasks.add_task(_unlink_path, zip_path)
        return FileResponse(zip_path, filename="cleanframe_batch.zip", media_type="application/zip")
    except HTTPException:
        _cleanup(zip_path)
        raise
    except Exception as exc:
        log.exception("strip-zip failed")
        _cleanup(zip_path)
        raise HTTPException(status_code=500, detail="Could not build the ZIP archive.") from exc


@app.post("/api/remove-bg", dependencies=[Depends(require_api_key_if_configured)])
async def api_remove_bg(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    strip_metadata: bool = Query(True, description="Re-encode output to strip metadata while keeping alpha"),
    exiftool_check: bool = Query(False),
):
    if not settings.rembg_available():
        raise HTTPException(status_code=501, detail="Background removal is not enabled on this server.")

    filename, suffix = _validate_upload_name(file)
    content = await _read_upload_limited(file)
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")

    tmp_raw: str | None = None
    tmp_out: str | None = None
    try:
        png_bytes, error = remove_background_png(content)
        if error or not png_bytes:
            raise HTTPException(status_code=422, detail=error or "Background removal failed.")

        if not strip_metadata:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as raw_file:
                tmp_raw = raw_file.name
                raw_file.write(png_bytes)
            tmp_out = tmp_raw
            tmp_raw = None
            output_name = f"{_safe_stem(filename)}_cutout.png"
            headers: dict[str, str] = {"X-Rembg-Stripped": "false"}
        else:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as raw_file:
                tmp_raw = raw_file.name
                raw_file.write(png_bytes)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as out_file:
                tmp_out = out_file.name
            result = strip_metadata_advanced(
                tmp_raw,
                tmp_out,
                quiet=True,
                preserve_alpha=True,
                output_format="png",
                jpeg_quality=95,
            )
            if not result.ok:
                raise HTTPException(status_code=422, detail=result.message)
            _unlink_path(tmp_raw)
            tmp_raw = None
            output_name = f"{_safe_stem(filename)}_cutout_clean.png"
            headers = {"X-Rembg-Stripped": "true", **_result_headers(result)}

        exif_summary = _maybe_exiftool(tmp_out, exiftool_check)
        if exiftool_check:
            headers["X-Exiftool-Summary"] = header_safe(exif_summary or "skipped")

        background_tasks.add_task(_unlink_path, tmp_out)
        return FileResponse(tmp_out, filename=output_name, media_type="image/png", headers=headers)
    except HTTPException:
        _cleanup(tmp_raw, tmp_out)
        raise
    except Exception as exc:
        log.exception("remove-bg failed")
        _cleanup(tmp_raw, tmp_out)
        raise HTTPException(status_code=500, detail="Could not remove the background.") from exc


def _read_static_html(name: str) -> str:
    path = STATIC_DIR / name
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        log.error("Static page missing: %s", path)
        raise HTTPException(status_code=503, detail=f"Missing static page: {name}.") from exc
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=503, detail=f"{name} must be valid UTF-8.") from exc


def _content_security_policy(path: str) -> str:
    if path.startswith("/api/docs") or path.startswith("/api/redoc"):
        return (
            "default-src 'self'; img-src 'self' data: https://fastapi.tiangolo.com; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
    return (
        "default-src 'self'; img-src 'self' blob: data:; style-src 'self'; "
        "script-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'"
    )


def _validate_upload_name(upload: UploadFile) -> tuple[str, str]:
    if not upload.filename:
        raise HTTPException(status_code=400, detail="Missing filename.")
    filename = Path(upload.filename).name
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise HTTPException(status_code=400, detail=f"Unsupported file type. Allowed: {allowed}.")
    if upload.content_type and not (
        upload.content_type.startswith("image/")
        or upload.content_type in {"application/octet-stream", "binary/octet-stream"}
    ):
        raise HTTPException(status_code=400, detail="Upload must be an image.")
    return filename, suffix


async def _read_upload_limited(upload: UploadFile) -> bytes:
    total = 0
    parts: list[bytes] = []
    while True:
        chunk = await upload.read(settings.read_chunk)
        if not chunk:
            break
        total += len(chunk)
        if total > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail=f"File too large. Max: {settings.max_upload_mb} MB.")
        parts.append(chunk)
    return b"".join(parts)


def _write_clean_image_to_zip(
    archive: zipfile.ZipFile,
    manifest: dict,
    filename: str,
    suffix: str,
    content: bytes,
    *,
    output: OutputFormat,
    preserve_alpha: bool,
    quality: int,
    exiftool_check: bool,
) -> None:
    input_path: str | None = None
    output_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as input_file:
            input_path = input_file.name
            input_file.write(content)
        with tempfile.NamedTemporaryFile(delete=False, suffix=_output_suffix(output, suffix)) as output_file:
            output_path = output_file.name

        result = strip_metadata_advanced(
            input_path,
            output_path,
            quiet=True,
            preserve_alpha=preserve_alpha,
            output_format=output,
            jpeg_quality=quality,
        )
        if not result.ok:
            manifest["files"].append({"original": filename, "error": result.message})
            return

        archive_name = f"{_safe_stem(filename)}_clean{Path(output_path).suffix.lower()}"
        archive.write(output_path, arcname=archive_name)
        entry = {
            "original": filename,
            "archive_path": archive_name,
            "input_bytes": result.input_bytes,
            "output_bytes": result.output_bytes,
            "metadata_remaining": result.metadata_remaining,
        }
        if exiftool_check:
            entry["exiftool"] = _maybe_exiftool(output_path, True)
        manifest["files"].append(entry)
    finally:
        _cleanup(input_path, output_path)


def _output_suffix(output: OutputFormat, fallback: str) -> str:
    if output == "jpeg":
        return ".jpg"
    if output == "png":
        return ".png"
    return fallback


def _safe_stem(filename: str) -> str:
    stem = SAFE_STEM_RE.sub("-", Path(filename).stem).strip("._-")
    return stem[:80] or "image"


def _result_headers(result) -> dict[str, str]:
    headers: dict[str, str] = {}
    if result.input_bytes is not None:
        headers["X-Input-Bytes"] = str(result.input_bytes)
    if result.output_bytes is not None:
        headers["X-Output-Bytes"] = str(result.output_bytes)
    if result.metadata_remaining is not None:
        headers["X-Metadata-Remaining"] = "true" if result.metadata_remaining else "false"
    return headers


def _maybe_exiftool(path: str | None, requested: bool) -> str | None:
    if not requested or not path:
        return None
    if not settings.exiftool_binary():
        return "skipped_no_exiftool_binary"
    return sensitive_tag_count(path)


def _unlink_path(path: str | None) -> None:
    if path:
        Path(path).unlink(missing_ok=True)


def _cleanup(*paths: str | None) -> None:
    for path in paths:
        _unlink_path(path)
