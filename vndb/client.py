"""Thin wrapper around the VNDB Kana API: throttling, retries, SQLite cache."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterator

import requests

from settings import DATA_DIR, load_config

RETRY_STATUSES = {429, 500, 502, 503, 504}


class VNDBError(RuntimeError):
    pass


class ResponseCache:
    """SQLite cache keyed by sha256 of (endpoint + canonical request body)."""

    def __init__(self, path: Path | str, ttl_seconds: float):
        self.path = str(path)
        self.ttl = ttl_seconds
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, ts REAL, body TEXT)"
            )
            self._conn.commit()

    @staticmethod
    def make_key(endpoint: str, body: dict) -> str:
        raw = endpoint + "\n" + json.dumps(body, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT ts, body FROM cache WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        ts, body = row
        if time.time() - ts > self.ttl:
            return None
        return json.loads(body)

    def set(self, key: str, value: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache (key, ts, body) VALUES (?, ?, ?)",
                (key, time.time(), json.dumps(value)),
            )
            self._conn.commit()


class VNDBClient:
    def __init__(
        self,
        config: dict | None = None,
        session: requests.Session | None = None,
        cache: ResponseCache | None = None,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        self.cfg = config or load_config()
        self.base = self.cfg["api_url"].rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update(
            {"User-Agent": self.cfg["user_agent"], "Content-Type": "application/json"}
        )
        self.cache = cache if cache is not None else ResponseCache(
            DATA_DIR / "cache.sqlite", self.cfg["cache_ttl_hours"] * 3600
        )
        self.min_interval = float(self.cfg["min_request_interval"])
        self.timeout = float(self.cfg["request_timeout"])
        self.max_retries = int(self.cfg["max_retries"])
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None
        self._lock = threading.Lock()

    # -- throttling -----------------------------------------------------
    def _throttle(self) -> None:
        if self._last_request is not None:
            wait = self.min_interval - (self._clock() - self._last_request)
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._clock()

    # -- core -----------------------------------------------------------
    def post(self, endpoint: str, body: dict, use_cache: bool = True) -> dict:
        endpoint = endpoint.strip("/")
        key = ResponseCache.make_key(endpoint, body)
        if use_cache:
            hit = self.cache.get(key)
            if hit is not None:
                return hit

        url = f"{self.base}/{endpoint}"
        backoff = 2.0
        last_err: str = ""
        with self._lock:
            for attempt in range(self.max_retries + 1):
                self._throttle()
                try:
                    resp = self.session.post(url, json=body, timeout=self.timeout)
                except requests.RequestException as e:
                    last_err = f"network error: {e}"
                else:
                    if resp.status_code == 200:
                        data = resp.json()
                        self.cache.set(key, data)
                        return data
                    if resp.status_code not in RETRY_STATUSES:
                        raise VNDBError(f"HTTP {resp.status_code}: {resp.text.strip()[:500]}")
                    last_err = f"HTTP {resp.status_code}"
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        backoff = max(backoff, float(retry_after))
                if attempt < self.max_retries:
                    self._sleep(backoff)
                    backoff = min(backoff * 2, 60)
        raise VNDBError(f"giving up after {self.max_retries + 1} attempts ({last_err})")

    def query(
        self,
        endpoint: str,
        filters: list | str | None = None,
        fields: str | list[str] = "",
        sort: str | None = None,
        reverse: bool = False,
        results: int = 10,
        page: int = 1,
        count: bool = False,
        use_cache: bool = True,
    ) -> dict:
        body: dict[str, Any] = {
            "fields": fields if isinstance(fields, str) else ", ".join(fields),
            "results": results,
            "page": page,
            "reverse": reverse,
        }
        if filters:
            body["filters"] = filters
        if sort:
            body["sort"] = sort
        if count:
            body["count"] = True
        return self.post(endpoint, body, use_cache=use_cache)

    def query_all(self, endpoint: str, max_pages: int = 1000, **kw) -> Iterator[dict]:
        """Yield every result across pages, following the `more` flag."""
        kw.setdefault("results", 100)
        for page in range(1, max_pages + 1):
            data = self.query(endpoint, page=page, **kw)
            yield from data.get("results", [])
            if not data.get("more"):
                return
