"""Download, cache and index the full VNDB tag list."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from settings import DATA_DIR, load_config

TAGS_PATH = DATA_DIR / "tags.json"
TAG_FIELDS = "name, aliases, category, searchable, applicable, vn_count"


@dataclass
class Tag:
    id: str
    name: str
    aliases: list[str]
    category: str          # cont | ero | tech
    searchable: bool
    applicable: bool
    vn_count: int


@dataclass
class TagIndex:
    tags: dict[str, Tag]                                    # id -> Tag
    by_text: dict[str, list[str]] = field(default_factory=dict)  # lowercase name/alias -> ids

    @classmethod
    def build(cls, tags: list[Tag]) -> "TagIndex":
        idx = cls({t.id: t for t in tags})
        for t in tags:
            for text in [t.name, *t.aliases]:
                key = text.strip().lower()
                if key:
                    idx.by_text.setdefault(key, [])
                    if t.id not in idx.by_text[key]:
                        idx.by_text[key].append(t.id)
        # Prefer the most-used tag when several share a name/alias.
        for ids in idx.by_text.values():
            ids.sort(key=lambda i: -idx.tags[i].vn_count)
        return idx

    def lookup(self, text: str) -> Tag | None:
        ids = self.by_text.get(text.strip().lower())
        return self.tags[ids[0]] if ids else None

    def by_name(self, name: str) -> Tag | None:
        """Exact (case-insensitive) match on the primary name only."""
        name = name.strip().lower()
        for tid in self.by_text.get(name, []):
            if self.tags[tid].name.lower() == name:
                return self.tags[tid]
        return None

    def __len__(self) -> int:
        return len(self.tags)


def fetch_tags(client) -> list[Tag]:
    out = []
    for r in client.query_all("tag", fields=TAG_FIELDS, sort="id", use_cache=False):
        if not r.get("searchable"):
            continue
        out.append(
            Tag(
                id=r["id"],
                name=r["name"],
                aliases=r.get("aliases") or [],
                category=r.get("category") or "cont",
                searchable=bool(r.get("searchable")),
                applicable=bool(r.get("applicable")),
                vn_count=int(r.get("vn_count") or 0),
            )
        )
    return out


def save_tags(tags: list[Tag], path: Path = TAGS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"fetched_at": time.time(), "tags": [t.__dict__ for t in tags]}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def read_tags(path: Path = TAGS_PATH) -> tuple[float, list[Tag]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["fetched_at"], [Tag(**t) for t in payload["tags"]]


def load_tag_index(client=None, refresh: bool = False, path: Path = TAGS_PATH,
                   config: dict | None = None, log=print) -> TagIndex:
    """Load tags.json, (re)downloading it if missing, stale, or refresh=True."""
    cfg = config or load_config()
    max_age = cfg["tag_refresh_days"] * 86400
    if path.exists() and not refresh:
        fetched_at, tags = read_tags(path)
        if time.time() - fetched_at < max_age:
            return TagIndex.build(tags)
        log(f"tags.json is older than {cfg['tag_refresh_days']} days, refreshing...")
    if client is None:
        from vndb.client import VNDBClient
        client = VNDBClient(cfg)
    log("Downloading VNDB tag list (about 30 requests, under a minute)...")
    tags = fetch_tags(client)
    save_tags(tags, path)
    log(f"Saved {len(tags)} searchable tags to {path}")
    return TagIndex.build(tags)
