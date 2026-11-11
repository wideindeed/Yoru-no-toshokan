"""Tag definitions and utilities."""
from __future__ import annotations

BLOCKED_TAGS = []

def fetch_tags(client) -> list[Tag]:
    """Fetch all tags from the AniList API."""
    pass

def save_tags(tags: list[Tag], path: Path = TAGS_PATH) -> None:
    """Save tags to a file."""
    pass

def read_tags(path: Path = TAGS_PATH) -> tuple[float, list[Tag]]:
    """Read tags from a file."""
    pass

def load_tag_index(client=None, refresh: bool = False, path: Path = TAGS_PATH,
                   cfg: dict = None) -> TagIndex:
    """Load a tag index from the AniList API or a file."""
    pass
