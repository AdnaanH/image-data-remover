# Image toolkit: FastAPI + optional rembg (needs RAM; use >= 2GB on the host).
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py server.py settings.py auth_deps.py exiftool_util.py bg_remove.py ./
COPY static ./static

ENV STRIP_HOST=0.0.0.0
# PORT is injected by Render/Railway/Fly; default for local docker run -p 8765:8765
ENV PORT=8765

EXPOSE 8765

CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
