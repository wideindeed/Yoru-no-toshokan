"""AniList GraphQL client: the same throttling, retries and SQLite cache as the VNDB client."""
from __future__ import annotations

from vndb.client import VNDBClient, VNDBError

API_URL = "https://graphql.anilist.co"


class AniListError(VNDBError):
    pass


class AniListClient(VNDBClient):
    def __init__(self, config: dict, **kw):
        # AniList allows 90 requests/min, temporarily 30 ("degraded"): stay under the lower one.
        super().__init__({**config, "api_url": API_URL,
                          "min_request_interval": config.get("anilist_min_interval", 2.1)}, **kw)

    def gql(self, query: str, variables: dict | None = None, use_cache: bool = True) -> dict:
        try:
            out = self.post("", {"query": query, "variables": variables or {}}, use_cache=use_cache)
        except VNDBError as e:
            raise AniListError(str(e)) from None
        if out.get("errors"):
            raise AniListError("; ".join(e.get("message", "?") for e in out["errors"])[:500])
        return out["data"]
