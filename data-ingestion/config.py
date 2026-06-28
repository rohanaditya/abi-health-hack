"""Load environment variables and expose typed settings."""

from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL: str = os.environ.get("API_BASE_URL", "https://hackathon.prod.pulsefoundry.ai")
DATABASE_URL: str | None = os.environ.get("DATABASE_URL")
MAX_RETRIES: int = int(os.environ.get("MAX_RETRIES", "8"))
WATERMARK_BUFFER_SECONDS: int = int(os.environ.get("WATERMARK_BUFFER_SECONDS", "300"))
FACILITIES: list[int] = [101, 102, 103]
SOURCE_CODE: str = "PCC"

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required. Copy .env.example to .env and fill it in.")
