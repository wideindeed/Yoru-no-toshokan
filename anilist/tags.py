"""Download, cache and index AniList's tag and genre lists (one request).

They reuse vndb.tags.Tag / TagIndex, so the parser, matcher and tag browser work unchanged:
  tags   -> id "t<number>", category "ero" if AniList marks it adult, else "cont"
  genres -> id "genre:<Name>", category "genre" ("Hentai" is "ero")
AniList has no aliases and no per-tag counts; nicknames come from synonyms.yaml.
"""
from __future__ import annotations

import time

from settings import DATA_DIR, load_config
from vndb.tags import Tag, TagIndex, read_tags, save_tags

TAGS_PATH = DATA_DIR / "anilist_tags.json"
ADULT_GENRES = {"Hentai"}
QUERY = "{MediaTagCollection{id name description category isAdult} GenreCollection}"


def is_genre(tag_id: str) -> bool:
    return tag_id.startswith("genre:")


def fetch_tags(client) -> list[Tag]:
    data = client.gql(QUERY, use_cache=False)
    out = [Tag(id=f"genre:{g}", name=g, aliases=[], category="ero" if g in ADULT_GENRES else "genre",
               searchable=True, applicable=True, vn_count=1, description=f"AniList genre: {g}.")
           for g in data["GenreCollection"]]
    for t in data["MediaTagCollection"]:
        out.append(Tag(id=f"t{t['id']}", name=t["name"], aliases=[],
                       category="ero" if t.get("isAdult") else "cont", searchable=True, applicable=True,
                       vn_count=0, description=(t.get("description") or "").strip()))
    return out


def load_tag_index(client=None, refresh: bool = False, path=TAGS_PATH,
                   config: dict | None = None, log=print) -> TagIndex:
    """Load anilist_tags.json, (re)downloading it if missing, stale, or refresh=True."""
    cfg = config or load_config()
    if path.exists() and not refresh:
        fetched_at, tags = read_tags(path)
        if time.time() - fetched_at < cfg["tag_refresh_days"] * 86400:
            return TagIndex.build(tags)
    if client is None:
        from anilist.client import AniListClient
        client = AniListClient(cfg)
    log("Downloading the AniList tag list (one request)...")
    tags = fetch_tags(client)
    save_tags(tags, path)
    log(f"Saved {len(tags)} AniList tags and genres to {path}")
    return TagIndex.build(tags)
