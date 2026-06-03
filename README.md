# CleanFrame

CleanFrame is a FastAPI image privacy workbench for stripping metadata from images, creating audited batch ZIPs, and optionally producing background-removed cut-outs. It is built as a portfolio-grade full-stack utility: practical UI, documented API, environment-only secrets, conservative upload limits, Docker support, and a package layout that is easy to extend.

## Live Staging

- Workbench: <https://cleanframe-staging.onrender.com/>
- Developer docs: <https://cleanframe-staging.onrender.com/docs>
- OpenAPI: <https://cleanframe-staging.onrender.com/api/docs>

## Features

- Re-encodes image pixels to remove EXIF, IPTC, XMP, ICC/profile metadata exposed through Pillow.
- Cleans single files or batches, with a `manifest.json` included in ZIP output.
- Optional ExifTool verification when an `exiftool` binary is available.
- Optional background removal through `rembg` and `onnxruntime`.
- API-key protection via `API_KEY`, using `Authorization: Bearer <key>` or `X-API-Key`.
- Security headers, bounded uploads, safe output names, and automatic temporary-file cleanup.
- Custom browser workbench at `/`, developer docs at `/docs`, and OpenAPI at `/api/docs`.

## Project Structure

```text
.
├── imagedataremover/
│   ├── api.py          # FastAPI app, routes, headers, validation
│   ├── auth.py         # Optional API-key dependency
│   ├── background.py   # Optional rembg integration
│   ├── config.py       # Environment settings
│   ├── exiftool.py     # Optional ExifTool checks
│   └── imaging.py      # Metadata-stripping core
├── static/
│   ├── css/
│   │   ├── app.css     # Workbench styles
│   │   └── docs.css    # Developer docs styles
│   ├── js/
│   │   └── app.js      # Workbench interactions
│   ├── index.html      # Workbench UI
│   └── docs.html       # Developer docs page
├── app.py              # CLI compatibility entry point
├── server.py           # Local server entry point
├── requirements.txt
└── requirements-ml.txt # Optional background-removal dependencies
```

## Local Setup

```powershell
cd "C:\Users\ahami\Desktop\Web Dev\image-data-remover"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python server.py
```

Open `http://127.0.0.1:8765`.

To enable background removal:

```powershell
pip install -r requirements-ml.txt
```

## Configuration

Copy `.env.example` to `.env` for local notes, but set real secrets in your hosting provider environment.

| Variable | Default | Purpose |
| --- | --- | --- |
| `API_KEY` | empty | Protects mutation endpoints when set. |
| `STRIP_HOST` | `127.0.0.1` | Local bind host. |
| `STRIP_PORT` | `8765` | Local port. Cloud `PORT` is also supported. |
| `STRIP_MAX_MB` | `25` | Per-file upload limit. |
| `STRIP_MAX_ZIP_TOTAL_MB` | `100` | Batch upload total limit. |
| `STRIP_MAX_BATCH_FILES` | `40` | Batch file count limit, clamped to 200. |
| `EXIFTOOL_PATH` | auto | Optional explicit ExifTool binary path. |
| `STRIP_ALLOWED_ORIGINS` | empty | Comma-separated CORS allowlist. |

## API Examples

Single image:

```bash
curl -X POST "http://127.0.0.1:8765/api/strip?output=png" \
  -F "file=@photo.jpg" \
  -o photo_clean.png
```

Authenticated batch:

```bash
curl -X POST "http://127.0.0.1:8765/api/strip-zip?preserve_alpha=true" \
  -H "Authorization: Bearer $API_KEY" \
  -F "files=@one.jpg" \
  -F "files=@two.png" \
  -o cleanframe_batch.zip
```

Background removal, when optional ML dependencies are installed:

```bash
curl -X POST "http://127.0.0.1:8765/api/remove-bg?strip_metadata=true" \
  -F "file=@portrait.jpg" \
  -o portrait_cutout_clean.png
```

## CLI

```powershell
python app.py photo.jpg
python app.py .\images --directory --format png --preserve-alpha
```

## Docker

Core image:

```bash
docker build -t cleanframe .
docker run --rm -p 8765:8765 -e API_KEY=replace-with-a-long-random-token cleanframe
```

With background removal:

```bash
docker build --build-arg INSTALL_REMBG=true -t cleanframe:ml .
```

## Security Notes

- Do not commit `.env` files, API keys, or generated uploads.
- Use a long random `API_KEY` for any public deployment.
- Put the app behind HTTPS on hosted infrastructure.
- Keep upload limits conservative; image processing can consume CPU and memory.
- Treat ExifTool as a verification aid, not a replacement for defense-in-depth.

## Verification

```powershell
python -m compileall imagedataremover app.py server.py
python server.py
```

Then visit `/health`, `/docs`, and `/api/docs`.
