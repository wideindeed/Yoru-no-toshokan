"""Load config.yaml with defaults. Paths are resolved relative to the project root."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

DEFAULTS = {
    "fuzzy_threshold": 85,
    "use_embeddings": False,
    "embedding_threshold": 0.55,
    "fuzzy_min_sort_ratio": 80,
    "high_rating_min": 70,
    "popular_min_votes": 500,
    "max_spoiler": 0,
    "min_tag_level": 1.2,
    "results_per_page": 24,
    "default_sort": "rating",
    "blur_sexual_level": 1,
    "blur_violence_level": 2,
    "cache_ttl_hours": 24,
    "tag_refresh_days": 7,
    "api_url": "https://api.vndb.org/kana",
    "user_agent": "vndb-finder-personal/0.1",
    "min_request_interval": 1.5,
    "request_timeout": 15,
    "max_retries": 5,
    "port": 5050,
    "use_llm": False,
    "llm_backend": "ollama",
    "llm_url": "http://127.0.0.1:11434",
    "llm_model": "qwen2.5:7b-instruct",
    "llm_timeout": 60,
    "llm_repair": True,
}


def load_config(path: Path | str | None = None) -> dict:
    path = Path(path) if path else ROOT / "config.yaml"
    cfg = dict(DEFAULTS)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            cfg.update(yaml.safe_load(f) or {})
    return cfg
