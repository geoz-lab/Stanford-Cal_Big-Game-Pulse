"""Load this project's .env before ttresearch reads its own, and pin the data dir here."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")  # wins over ../tiktok_data/.env (load_dotenv never overrides)
_dd = Path(os.getenv("TTR_DATA_DIR", "data"))
DATA_DIR = _dd if _dd.is_absolute() else ROOT / _dd
os.environ["TTR_DATA_DIR"] = str(DATA_DIR)
DATA_DIR.mkdir(parents=True, exist_ok=True)
