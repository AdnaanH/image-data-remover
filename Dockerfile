# CleanFrame: FastAPI image privacy workbench.
FROM python:3.12-slim-bookworm

ARG INSTALL_REMBG=false

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-ml.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_REMBG" = "true" ]; then pip install --no-cache-dir -r requirements-ml.txt; fi

COPY imagedataremover ./imagedataremover
COPY static ./static
COPY app.py server.py ./

ENV STRIP_HOST=0.0.0.0
ENV PORT=8765

EXPOSE 8765

CMD ["sh", "-c", "exec uvicorn imagedataremover.api:app --host 0.0.0.0 --port ${PORT}"]
