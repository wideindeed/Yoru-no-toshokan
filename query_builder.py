"""ParseResult -> Kana /vn filter JSON, plus result-card shaping."""
from __future__ import annotations

from itertools import combinations

from parsing.model import Criterion, ParseResult
from vndb.tags import BLOCKED_TAGS

VN_FIELDS = ", ".join([
    "id", "title", "alttitle", "released", "rating", "votecount", "length",
    "image.url", "image.thumbnail", "image.sexual", "image.violence",
    "tags.id", "tags.name", "tags.rating", "tags.spoiler", "tags.category",
    "developers.name",
])
SORTS = {"rating", "votecount", "released", "title", "soonest"}


def api_sort(sort: str) -> tuple[str, bool]:
    """Our sort name -> (VNDB sort field, reverse). "soonest" is release date, oldest first."""
    return ("released" if sort == "soonest" else sort), sort not in ("title", "soonest")

_INVERT = {">=": "<", "<": ">=", ">": "<=", "<=": ">", "=": "!=", "!=": "="}


def _and(parts: list):
    parts = [p for p in parts if p]
    return None if not parts else parts[0] if len(parts) == 1 else ["and", *parts]


def _or(parts: list):
    parts = [p for p in parts if p]
    return None if not parts else parts[0] if len(parts) == 1 else ["or", *parts]


def _tag(tid: str, c: Criterion, cfg: dict, op: str = "=") -> list:
    if op == "!=":   # exclusions are strict: any vote strength, spoiler or not
        return ["tag", "!=", [tid, 2, 0.0]]
    lvl = c.min_level if c.min_level is not None else cfg["min_tag_level"]
    return ["tag", op, [tid, int(cfg["max_spoiler"]), float(lvl)]]


def criterion_filter(c: Criterion, cfg: dict):
    """One criterion -> one filter expression (exclusion already applied)."""
    ex = c.exclude
    if c.soft:              # mood hints only re-rank (see build_filters for the one exception)
        return None
    if c.kind == "tag":
        return _tag(c.value, c, cfg, "!=" if ex else "=")
    if c.kind == "tag_any":
        if ex:   # none of them
            return _and([_tag(t, c, cfg, "!=") for t in c.value])
        return _or([_tag(t, c, cfg) for t in c.value])
    if c.kind in ("lang", "platform"):
        if ex:
            return _and([[c.kind, "!=", v] for v in c.value])
        return _or([[c.kind, "=", v] for v in c.value])
    if c.kind == "engine":
        return ["release", "!=" if ex else "=", ["engine", "=", c.value]]
    if c.kind == "released":
        if ex:   # NOT (a AND b) = (NOT a) OR (NOT b)
            return _or([["released", _INVERT[op], d] for op, d in c.value])
        return _and([["released", op, d] for op, d in c.value])
    if c.kind == "tl":      # a release in that language, by the publisher (official) or not (fan)
        code, official = c.value
        rel = ["and", ["lang", "=", code], ["official", "=" if official else "!=", 1]]
        return ["release", "!=" if ex else "=", rel]
    if c.kind == "id":
        return ["id", "!=" if ex else "=", c.value]
    if c.kind == "like":    # expanded into tags before searching; never a filter itself
        return None
    if c.kind == "title":   # VNDB's own title search (titles, aliases, release titles)
        return ["search", "=", str(c.value)[:200]]   # never an exclusion
    if c.kind in ("length", "rating", "votecount"):
        op = c.op if c.kind == "length" else (c.op or ">=")
        return [c.kind, _INVERT[op] if ex else op, c.value]
    raise ValueError(f"unknown kind {c.kind}")


SEXUAL_CONTENT, NO_SEXUAL_CONTENT = "g23", "g235"


def content_in_query(crits: list[Criterion]) -> bool:
    """True if the query itself sets a content level (explicit / suggestive / all ages),
    which then takes precedence over the Mature toggle."""
    for c in crits:
        ids = c.value if c.kind == "tag_any" else [c.value] if c.kind == "tag" else []
        if SEXUAL_CONTENT in ids or NO_SEXUAL_CONTENT in ids or c.label.startswith("Content:"):
            return True
    return False


BLOCK_FILTERS = [["tag", "!=", [t, 2, 0.0]] for t in sorted(BLOCKED_TAGS)]   # in every search, always


def mature_filter(mature: bool, cfg: dict) -> list:
    """Mature on: only VNs tagged Sexual Content (or any child tag).
    Off: none of them, at any spoiler level and any vote strength."""
    if mature:
        return ["tag", "=", [SEXUAL_CONTENT, 2, float(cfg["min_tag_level"])]]
    return ["tag", "!=", [SEXUAL_CONTENT, 2, 0.0]]


def build_filters(res: ParseResult | list[Criterion], cfg: dict, mode: str = "all",
                  mature: bool | None = None):
    """mode 'all': every criterion must hold.
    mode 'any': positive tag criteria are OR'ed (re-rank locally); the rest still AND.
    mature: True/False adds the Mature filter (unless the query sets a content level);
    "all" (Everything) and None add none."""
    crits = res.criteria if isinstance(res, ParseResult) else res
    extra = BLOCK_FILTERS + ([mature_filter(mature, cfg)] if mature in (True, False) and not content_in_query(crits) else [])
    moods = [c for c in crits if c.soft and not c.exclude]
    if moods and not any(c.kind in ("tag", "tag_any") and not (c.exclude or c.soft) for c in crits):
        # only mood words ("something dark and cute"): any one of their tags, else nothing narrows
        extra.append(_or([_tag(t, c, cfg) for c in moods for t in c.value]))
    if mode == "any":
        pos_tags = [c for c in crits if c.kind in ("tag", "tag_any") and not (c.exclude or c.soft)]
        rest = [c for c in crits if c not in pos_tags]
        return _and([_or([criterion_filter(c, cfg) for c in pos_tags]),
                     *[criterion, criterion_filter(c, cfg) for c in rest], *extra])
    return _and([criterion_filter(c, cfg) for c in crits] + extra)


def relaxed(crits: list[Criterion], budget: int = 8) -> list[list[list[Criterion]]]:
    """Close matches for an all-tags search that found too little: first one wanted tag
    swapped for its related tags, then 1, 2, ... of the wanted tags left out, as levels of
    criteria lists (at most `budget` lists in all). Everything else (length, language,
    excludes) stays."""
    pos = [i for i, c in enumerate(crits) if c.kind in ("tag", "tag_any") and not (c.exclude or c.soft)]
    levels = []
    swaps = [[Criterion("tag_any", c.related, c.label, min_level=c.min_level) if j == i else c
              for j, c in enumerate(crits)] for i in pos if (c := crits[i]).related][:budget // 2]
    if swaps:
        levels.append(swaps)
        budget -= len(swaps)
    for drop in range(1, len(pos)):
        level = []
        for left_out in combinations(pos, drop):
            if budget <= 0:
                break
            level.append([c for i, c in enumerate(crits) if i not in left_out])
            budget -= 1
        if level:
            levels.append(level)
    return levels


def rank_close(cards: list[dict], sort: str, limit: int) -> list[dict]:
    """Close matches: most wanted tags first, then related stand-ins, mood hints and the
    chosen sort; marked for the UI."""
    key = {"rating": "rating", "votecount": "votecount", "released": "year"}.get(sort)
    cards = sorted(cards, key=lambda c: (-c["hits"], -c.get("near", 0), -c.get("hint", 0),
                                         -float(c.get(key) or 0) if key else 0))
    return [{**c, "close": True} for c in cards[:limit]]


def close_note(n_all: int) -> str:
    return (f"{n_all or 'No'} VN{' has' if n_all == 1 else 's have'} all your tags; "
            "closest matches follow, marked with how many they have.")


def wanted_tag_groups(crits: list[Criterion]) -> list[tuple]:
    """Each positive tag criterion as (acceptable ids, lowercase names, label, related ids,
    mood) for re-ranking; mood hints (+1 wanted, -1 not wanted) never count as hits.
    Names let child tags count too: VNDB's tag filter matches "Vampire Heroine"
    for "Vampire", but the VN only lists the child's id."""
    out = []
    for c in crits:
        if c.kind not in ("tag", "tag_any") or (c.exclude and not c.soft):
            continue
        ids = {c.value} if c.kind == "tag" else set(c.value)
        names = [n.strip().lower() for n in c.label.split(" / ")] if not c.soft and (c.kind == "tag" or "/" in c.label) else []
        mood = (-1 if c.exclude else 1) if c.soft else 0
        out.append((ids, names, c.label, set(c.related or ()), mood))
    return out


def order(cards: list[dict], mode: str) -> list[dict]:
    """Any-tags mode: most wanted tags first. Then mood hints. Stable: keeps API order otherwise."""
    return sorted(cards, key=lambda c: (-c["hits"] if mode == "any" else 0, -c.get("hint", 0)))


def _hit(group, vn_tags: list[dict]) -> bool:
    ids, names = group[0], group[1]
    return any(t["id"] in ids or any(n and n in (t.get("name") or "").lower() for n in names)
               for t in vn_tags)


def to_card(vn: dict, cfg: dict, groups: list[set[str]] = (), show_explicit: bool = False) -> dict:
    tags = [t for t in vn.get("tags") or [] if t.get("spoiler", 0) == 0
            and (t.get("category") == "cont" or (show_explicit and t.get("category") == "ero"))]
    tags.sort(key=lambda t: -(t.get("rating") or 0))
    img = vn.get("image") or {}
    sexual, violence = img.get("sexual") or 0, img.get("violence") or 0
    return {
        "id": vn["id"],
        "url": f"https://vndb.org/{vn['id']}",
        "title": vn.get("title"),
        "alttitle": vn.get("alttitle"),
        "year": (vn.get("released") or "")[:4] or None,
        "rating": round(vn["rating"] / 10, 2) if vn.get("rating") else None,
        "votecount": vn.get("votecount"),
        "developers": [d["name"] for d in vn.get("developers") or []][:2],
        "tags": [t["name"] for t in tags[:5]],
        "cover": img.get("thumbnail") or img.get("url"),
        "cover_full": img.get("url"),
        "blur": bool(img) and not show_explicit and (sexual >= cfg["blur_sexual_level"] or violence >= cfg["blur_violence_level"]),
        **hit_summary(groups, vn.get("tags") or []),
    }


def hit_summary(groups, item_tags: list[dict]) -> dict:
    """How many wanted tags a title has, and which ones it lacks (shown on the card)."""
    hard = [g for g in groups if not (len(g) > 4 and g[4])]
    lacking = [g for g in hard if not _hit(g, item_tags)]
    ids = {t["id"] for t in item_tags}
    return {"hits": len(hard) - len(lacking), "wanted": len(hard), "missing": [g[2] for g in lacking],
            "near": sum(1 for g in lacking if len(g) > 3 and g[3] & ids),
            "hint": sum(g[4] for g in groups if len(g) > 4 and g[4] and g[0] & ids)}
