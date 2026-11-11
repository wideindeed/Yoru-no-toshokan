"""Search by example: a title's most telling tags as criteria ("more like this"),
in the same library or mapped onto the other one (visual novel <-> light novel),
and the same idea over a whole VNDB list ("for you").

Pure functions (no network), so the browser version uses them too.
"""
from __future__ import annotations

import json
import math
import re

from parsing.model import Criterion
from vndb.tags import TagIndex

N_TAGS = 4          # more than this and few titles have them all (close matches fill in)
MIN_RATING = 1.5          # VNDB tag score 0-3; weaker votes say little about a title


def vn_tags(vn: dict) -> list[dict]:
    """VNDB tags as {id, rating, spoiler, category}."""
    return [{"id": t["id"], "rating": t.get("rating") or 0, "spoiler": t.get("spoiler") or 0,
             "category": t.get("category") or "cont"} for t in vn.get("tags") or []]


def ln_tags(media: dict) -> list[dict]:
    """AniList tags (rank 0-100) and genres on the same 0-3 scale as VNDB's."""
    out = [{"id": f"t{t['id']}", "rating": (t.get("rank") or 0) * 3 / 100,
            "spoiler": 1 if t.get("isMediaSpoiler") or t.get("isGeneralSpoiler") else 0,
            "category": "ero" if t.get("isAdult") else "cont"} for t in media.get("tags") or []]
    return out + [{"id": f"genre:{g}", "rating": 2.0, "spoiler": 0, "category": "cont"}
                  for g in media.get("genres") or [] if g != "Hentai"]


_PERSON = re.compile(r"(?:Heroine|Protagonist|Hero|Friends?|Sisters?|Brothers?|Mother|Father|Childhood)")

# --- fetching a title (the caller sends these; no network here) -------------------
VN_FIELDS = "title, votecount, tags.id, tags.rating, tags.spoiler, tags.category"
_LN_FIELDS = "id isAdult title{romaji english} tags{id rank isMediaSpoiler isGeneralSpoiler isAdult} genres"


def vn_request(vid: str | None = None, search: str | None = None) -> dict:
    """Body for VNDB's /vn: one VN by id, or the best title match."""
    if vid:
        return {"filters": ["id", "=", vid], "fields": VN_FIELDS, "results": 1}
    return {"filters": ["search", "=", search[:200]], "fields": VN_FIELDS, "sort": "searchrank", "results": 5}


def best_vn(rows: list[dict]) -> dict | None:
    """Of the top title matches, the best known ("Ever17" is the original, not its remake)."""
    return max(rows, key=lambda r: r.get("votecount") or 0) if rows else None


def ln_request(lid: str | None = None, search: str | None = None) -> str:
    """AniList query: one light novel by "l<id>", or the best title match."""
    arg = f"id: {int(lid[1:])}" if lid else "search: " + json.dumps(search[:200])
    return f"{{ Media({arg}, type: MANGA, format: NOVEL) {{ {_LN_FIELDS} }} }}"


def from_vn(row: dict | None) -> tuple[str, str, list[dict]] | None:
    return (row["id"], row.get("title") or row["id"], vn_tags(row)) if row else None


def from_ln(media: dict | None) -> tuple[str, str, list[dict]] | None:
    if not media:
        return None
    t = media.get("title") or {}
    return f"l{media['id']}", t.get("english") or t.get("romaji") or f"l{media['id']}", ln_tags(media)


# --- a VNDB user's list ------------------------------------------------------------
LIST_PAGES = 10           # 100 entries a page: the first 1000 (best voted first)
SEEN_LABELS = {1, 2, 3, 4, 6}   # playing, finished, stalled, dropped, blacklist (not wishlist)


def user_url(api: str, name: str) -> str:
    from urllib.parse import quote
    return f"{api.rstrip('/')}/user?q={quote(name.strip()[:50])}"


def user_id(resp: dict, name: str) -> tuple[str, str] | None:
    """GET /user?q=name -> (id, username), or None if there is no such user."""
    u = next(iter(resp.values()), None) if resp else None
    return (u["id"], u["username"]) if u else None


def ulist_request(uid: str, page: int) -> dict:
    return {"user": uid, "fields": "vote, labels.id, " + ", ".join("vn." + f.strip() for f in VN_FIELDS.split(",")),
            "sort": "vote", "reverse": True, "results": 100, "page": page}


def read_list(rows: list[dict], index: TagIndex) -> dict:
    """/ulist results -> {"items": {vid: vote 10-100 or 0}, "taste": [criterion dicts]}.
    Only titles someone played, voted on or blacklisted count; a wishlist does not."""
    items, entries = {}, []
    for r in rows:
        labels = {lab["id"] for lab in r.get("labels") or []}
        if r.get("vote") or labels & SEEN_LABELS:
            items[r["id"]] = r.get("vote") or 0
            entries.append({"vote": r.get("vote"), "tags": vn_tags(r.get("vn") or {})})
    return {"items": items, "taste": [c.to_dict() for c in taste(entries, index)]}


def like_criteria(found, source: str, index: TagIndex, target_source: str, target=None) -> list[Criterion]:
    """found: from_vn / from_ln output. Tag criteria for the target library, plus
    "not this title" when it is the same library."""
    if not found:
        return []
    item_id, title, tags = found
    crits = similar(tags, index, title, target if target_source != source else None)
    if crits and target_source == source:
        crits.append(Criterion("id", item_id, title, exclude=True, phrase=f"like {title}", method="like"))
    return crits


def _score(t: dict, index: TagIndex) -> float:
    """How well a tag describes a title: its score first, then how specific it is
    ("Amnesia" says more than "Male Protagonist"; a tag on a few dozen VNs finds nothing)."""
    tag = index.tags.get(t["id"])
    if tag is None or t["spoiler"] or t["category"] != "cont" or t["rating"] < MIN_RATING:
        return 0.0
    if tag.category == "genre":
        return (t["rating"] - 1) ** 2 * 0.9
    if tag.vn_count and not 80 <= tag.vn_count <= 10000:
        return 0.0
    spec = 1 + 0.3 * math.log10(40000 / (tag.vn_count + 100)) if tag.vn_count else 1.2
    if _PERSON.search(tag.name):   # character traits describe one cast, not the story
        spec *= 0.6
    return (t["rating"] - 1) ** 2 * spec


def _ranked(tags: list[dict], index: TagIndex) -> list[str]:
    scored = sorted(((_score(t, index), t["id"]) for t in tags), reverse=True)
    return [tid for s, tid in scored if s > 0]


def _criteria(tag_ids: list[str], index: TagIndex, phrase: str, method: str,
              target=None, n: int = N_TAGS) -> list[Criterion]:
    """target: (index, matcher) of the other library: tags are carried over by name."""
    out: list[Criterion] = []
    for tid in tag_ids:
        name = index.tags[tid].name
        if target is None:
            found = [Criterion("tag", tid, name)]
        else:
            t_index, t_matcher = target
            m = t_matcher.lookup_exact(name)
            found = [c for c in (m.criteria if m else []) if c.kind in ("tag", "tag_any") and not c.exclude
                     and all(t_index.tags[i].category != "ero"
                             for i in ([c.value] if c.kind == "tag" else c.value) if i in t_index.tags)]
        for c in found[:1]:
            if all(c.key() != x.key() for x in out):
                c.phrase, c.method = phrase, method
                out.append(c)
        if len(out) >= n:
            break
    return out


def similar(tags: list[dict], index: TagIndex, title: str, target=None, n: int = N_TAGS) -> list[Criterion]:
    """A title's tags (from vn_tags / ln_tags) -> up to n tag criteria."""
    return _criteria(_ranked(tags, index), index, f"like {title}", "like", target, n)


def taste(entries: list[dict], index: TagIndex, n: int = N_TAGS) -> list[Criterion]:
    """entries: [{"vote": 10-100, "tags": vn_tags(...)}] from a VNDB list. Tags of the
    titles someone rated highly, weighted by how much they liked each."""
    total: dict[str, float] = {}
    for e in entries:
        vote = e.get("vote") or 0
        if vote < 60:
            continue
        w = (vote - 50) / 50
        for t in e["tags"]:
            if s := _score(t, index):
                total[t["id"]] = total.get(t["id"], 0) + w * s
    ranked = sorted(total, key=lambda i: -total[i])
    return _criteria(ranked, index, "your VNDB list", "your list", None, n)
