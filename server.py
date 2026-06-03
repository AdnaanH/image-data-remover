"""Local development entry point.

Run:
    python server.py
"""

from __future__ import annotations

import uvicorn

from imagedataremover.api import app
from imagedataremover.config import settings


if __name__ == "__main__":
    uvicorn.run(
        "imagedataremover.api:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
