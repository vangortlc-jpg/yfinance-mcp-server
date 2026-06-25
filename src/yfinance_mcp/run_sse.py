"""Entry point for cloud deployment (Render, etc.)."""
import logging
import os
import uvicorn
from .server import create_sse_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

app = create_sse_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
