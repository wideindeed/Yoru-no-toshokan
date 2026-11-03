"""Criteria -> AniList GraphQL for light novels, plus card and detail shaping.

AniList's tag_in is AND-only, so OR (tag_any, "any tag" mode) becomes several aliased
Page queries in ONE request (q0, q1, ...), merged here. Pure functions (no network),
so the browser version (web/web.py) uses them too.
"""
from __future__ import annotations

import html
import itertools
import json
import re

import query_builder as qb
from anilist.tags import is_genre
from parsing.model import Criterion
from vndb.tags import TagIndex

SORTS = {"rating": ["SCORE_DESC", "POPULARITY_DESC"], "votecount": ["POPULARITY_DESC"],
         "released": ["START_DATE_DESC", "POPULARITY_DESC"], "title": ["TITLE_ROMAJI"]}
UNSUPPORTED = {"lang", "platform", "engine", "length"}
MAX_VARIANTS = 8
CARD_FIELDS = ("id title{romaji english native} startDate{year} averageScore popularity volumes status "
               "isAdult coverImage{large medium} genres tags{id name rank isMediaSpoiler isAdult} "
               "staff(perPage:4){edges{role node{name{full}}}}")
DETAIL_FIELDS = ("id siteUrl title{romaji english native} synonyms description startDate{year month day} "
                 "endDate{year month day} status volumes chapters averageScore popularity favourites "
                 "countryOfOrigin isAdult coverImage{extraLarge large} genres "
                 "tags{id name rank category isMediaSpoiler isGeneralSpoiler isAdult} "
                 "staff(perPage:12){edges{role node{name{full}}}} "
                 "relations{edges{relationType node{id type format siteUrl title{romaji english} "
                 "startDate{year} coverImage{medium} isAdult}}} externalLinks{url site}")
STATUS = {"FINISHED": "Finished", "RELEASING": "Ongoing", "NOT_YET_RELEASED": "Not yet released",
          "CANCELLED": "Cancelled", "HIATUS": "On hiatus"}
FORMATS = {"NOVEL": "Light novel", "MANGA": "Manga", "ONE_SHOT": "One-shot", "TV": "Anime",
           "TV_SHORT": "Anime (short)", "MOVIE": "Movie", "OVA": "OVA", "ONA": "ONA", "SPECIAL": "Special",
           "MUSIC": "Music video"}
LN_PREFIX = "l"   # light novel ids: "l" + AniList media id (VN ids are "v...")


def ln_id(media_id: int) -> str:
    return f"{LN_PREFIX}{media_id}"


def media_id(lid: str) -> int | None:
    m = re.fullmatch(r"l(\d{1,9})", str(lid))
    return int(m[1]) if m else None


def _lit(v) -> str:
    """Python value -> GraphQL literal (JSON strings/lists are valid GraphQL)."""
    if isinstance(v, bool):
        return "true" if v else "false"
    return json.dumps(v, ensure_ascii=False)


def _names(c: Criterion, index: TagIndex) -> list[str]:
    ids = [c.value] if c.kind == "tag" else c.value if c.kind == "tag_any" else []
    return [i for i in ids if i in index.tags]


def _date(d: str) -> int:
    return int(d.replace("-", "")[:8].ljust(8, "0"))


def is_adult_crit(c: Criterion, index: TagIndex) -> bool:
    return not c.exclude and any(index.tags[i].category == "ero" for i in _names(c, index))


def build(crits: list[Criterion], index: TagIndex, cfg: dict, mode: str = "all", mature: bool = False,
          page: int = 1, sort: str = "rating", hidden=(), per_page: int | None = None) -> tuple[str, list[str]]:
    """-> (GraphQL query text, notes for the user)."""
    notes: list[str] = []
    base: dict = {}
    skipped = []

    def add(key, v):
        base.setdefault(key, [])
        if v not in base[key]:
            base[key].append(v)

    positives: list[list[str]] = []          # each: acceptable tag ids (OR)
    for c in crits:
        if c.kind in UNSUPPORTED:
            skipped.append(c.label)
        elif c.kind in ("tag", "tag_any"):
            ids = _names(c, index)
            if c.exclude:
                for i in ids:
                    add("genre_not_in" if is_genre(i) else "tag_not_in", index.tags[i].name)
            elif ids:
                positives.append(ids)
        elif c.kind == "released":
            bounds = c.value
            if c.exclude:
                if len(bounds) != 1:
                    skipped.append("NOT " + c.label)
                    continue
                bounds = [[qb._INVERT[bounds[0][0]], bounds[0][1]]]
            for op, d in bounds:
                n = _date(d)
                jan1 = n % 10000 == 101   # year bounds; AniList stores a year-only date as YYYY0000
                if op in (">=", ">"):
                    base["startDate_greater"] = (n // 10000 - 1) * 10000 + 9999 if op == ">=" and jan1                         else n - 1 if op == ">=" else n
                else:
                    base["startDate_lesser"] = n // 10000 * 10000 if op == "<" and jan1 else n if op == "<" else n + 1
        elif c.kind in ("rating", "votecount"):
            key = "averageScore" if c.kind == "rating" else "popularity"
            v = int(c.value)
            if c.exclude:
                base[f"{key}_lesser"] = v
            else:
                base[f"{key}_greater"] = v - 1
        elif c.kind == "title":
            base["search"] = str(c.value)[:200]
    if skipped:
        notes.append("Not used for light novels: " + ", ".join(skipped) + ".")

    # Mature off: no adult titles. On: adult titles included. Asking for adult tags overrides.
    if not mature and not any(is_adult_crit(c, index) for c in crits):
        base["isAdult"] = False
    ids_hidden = [m for h in hidden if (m := media_id(h)) is not None]
    if ids_hidden:
        base["id_not_in"] = ids_hidden

    if mode == "any" and positives:
        flat = list(dict.fromkeys(i for alts in positives for i in alts))
        variants = [[i] for i in flat]
    else:
        variants = [list(v) for v in itertools.product(*positives)] if positives else [[]]
    if len(variants) > MAX_VARIANTS:
        notes.append(f"Too many alternatives; only the first {MAX_VARIANTS} combinations were searched.")
        variants = variants[:MAX_VARIANTS]

    n = int(per_page or cfg["results_per_page"])
    if len(variants) > 1:
        n = max(6, n // len(variants) + 2)
    parts = []
    for k, ids in enumerate(variants):
        args = dict(base)
        for i in ids:
            args.setdefault("genre_in" if is_genre(i) else "tag_in", []).append(index.tags[i].name)
        if "tag_in" in args:
            args["minimumTagRank"] = int(cfg.get("ln_min_tag_rank", 50))
        arg_text = ", ".join(f"{key}: {_lit(v)}" for key, v in args.items())
        sort_text = ", ".join(SORTS.get(sort, SORTS["rating"]))
        parts.append(f"q{k}: Page(page: {int(page)}, perPage: {n}) {{ pageInfo {{ hasNextPage }} "
                     f"media(type: MANGA, format: NOVEL, sort: [{sort_text}]{', ' + arg_text if arg_text else ''}) "
                     f"{{ {CARD_FIELDS} }} }}")
    return "{ " + " ".join(parts) + " }", notes


def merge(data: dict, sort: str = "rating") -> tuple[list[dict], bool]:
    """Aliased pages -> (media, more), deduplicated and re-sorted."""
    pages = [data[k] for k in sorted(data, key=lambda k: int(k[1:]))]
    seen, media = set(), []
    for p in pages:
        for m in p.get("media") or []:
            if m["id"] not in seen:
                seen.add(m["id"])
                media.append(m)
    if len(pages) > 1:
        key = {"rating": lambda m: (-(m.get("averageScore") or 0), -(m.get("popularity") or 0)),
               "votecount": lambda m: -(m.get("popularity") or 0),
               "released": lambda m: -((m.get("startDate") or {}).get("year") or 0),
               "title": lambda m: _title(m)[0].lower()}.get(sort)
        if key:
            media.sort(key=key)
    return media, any((p.get("pageInfo") or {}).get("hasNextPage") for p in pages)


def _title(m: dict) -> tuple[str, str | None]:
    t = m.get("title") or {}
    main = t.get("english") or t.get("romaji") or t.get("native") or "?"
    alt = t.get("romaji") if t.get("english") and t.get("romaji") != main else t.get("native")
    return main, alt if alt != main else None


def _media_tags(m: dict) -> list[dict]:
    """Tags + genres as {id, name} for qb's re-ranking."""
    return ([{"id": f"t{t['id']}", "name": t["name"]} for t in m.get("tags") or []]
            + [{"id": f"genre:{g}", "name": g} for g in m.get("genres") or []])


def _authors(m: dict, n: int = 2) -> list[str]:
    edges = (m.get("staff") or {}).get("edges") or []
    story = [e for e in edges if re.match(r"(original\s+)?(story|creator)", (e.get("role") or ""), re.I)]
    return list(dict.fromkeys(e["node"]["name"]["full"] for e in story or edges))[:n]


def to_card(m: dict, cfg: dict, groups=(), show_explicit: bool = False) -> dict:
    tags = [t for t in m.get("tags") or [] if not t.get("isMediaSpoiler") and (show_explicit or not t.get("isAdult"))]
    tags.sort(key=lambda t: -(t.get("rank") or 0))
    names = [t["name"] for t in tags[:5]]
    names += [g for g in m.get("genres") or [] if g not in names and (show_explicit or g != "Hentai")][:5 - len(names)]
    cover = m.get("coverImage") or {}
    title, alt = _title(m)
    return {
        "id": ln_id(m["id"]),
        "url": f"https://anilist.co/manga/{m['id']}",
        "title": title,
        "alttitle": alt,
        "year": str((m.get("startDate") or {}).get("year") or "") or None,
        "rating": round(m["averageScore"] / 10, 2) if m.get("averageScore") else None,
        "votecount": m.get("popularity"),
        "developers": _authors(m),
        "volumes": m.get("volumes"),
        "tags": names,
        "cover": cover.get("medium") or cover.get("large"),
        "cover_full": cover.get("large"),
        "blur": bool(m.get("isAdult")) and not show_explicit,
        "hits": sum(1 for g in groups if qb._hit(g, _media_tags(m))),
        "wanted": len(groups),
    }


def tag_url(name: str) -> str:
    """AniList's browse page; it takes tags and genres in the same parameter."""
    from urllib.parse import quote
    return f"https://anilist.co/search/manga?format=NOVEL&genres={quote(name)}"


def detail_query(mid: int) -> str:
    return f"{{ Media(id: {int(mid)}, type: MANGA) {{ {DETAIL_FIELDS} }} }}"


_ALLOWED = re.compile(r"&lt;(/?)(br|i|b|em|strong)\s*/?&gt;", re.I)


def description(text: str | None) -> str:
    """AniList description (light HTML + ~!spoiler!~) -> safe HTML. Escaped first,
    then only <br>, <i>, <b>, <em>, <strong> come back."""
    if not text:
        return ""
    s = html.escape(text, quote=True)
    s = _ALLOWED.sub(lambda m: f"<{m[1]}{m[2].lower()}>", s)
    s = re.sub(r"~!(.*?)!~", r'<span class="spoiler" title="click to reveal">\1</span>', s, flags=re.S)
    s = re.sub(r"\s*\n\s*", "<br>", s.strip())
    return re.sub(r"(?:<br>\s*){3,}", "<br><br>", s)


def _fdate(d: dict | None) -> str | None:
    d = d or {}
    if not d.get("year"):
        return None
    return "-".join(f"{v:02d}" if i else str(v) for i, v in enumerate([d["year"], d.get("month"), d.get("day")]) if v)


def shape(m: dict, cfg: dict, mature: bool = False) -> dict:
    """One light novel for the detail page (same keys the VN page uses, plus a few)."""
    tags = sorted(m.get("tags") or [], key=lambda t: -(t.get("rank") or 0))
    groups = []
    if m.get("genres"):
        groups.append({"label": "Genres", "tags": [
            {"id": f"genre:{g}", "name": g, "rating": None, "spoiler": 0,
             "url": tag_url(g)}
            for g in m["genres"] if mature or g != "Hentai"]})
    for label, adult in (("Tags", False), ("Sexual content", True)):
        if adult and not mature:
            continue
        items = [{"id": f"t{t['id']}", "name": t["name"], "rating": t.get("rank"),
                  "spoiler": 2 if t.get("isMediaSpoiler") else 1 if t.get("isGeneralSpoiler") else 0,
                  "url": tag_url(t["name"])}
                 for t in tags if bool(t.get("isAdult")) == adult]
        if items:
            groups.append({"label": label, "tags": items})

    staff: dict[str, list[str]] = {}
    for e in (m.get("staff") or {}).get("edges") or []:
        role = re.sub(r"\s*\(.*\)$", "", e.get("role") or "Staff").strip()
        if re.search(r"translat|letter|edit|touch-up|proofread|typeset", role, re.I):
            continue
        staff.setdefault(role, [])
        if e["node"]["name"]["full"] not in staff[role]:
            staff[role].append(e["node"]["name"]["full"])

    relations = []
    for e in (m.get("relations") or {}).get("edges") or []:
        n = e.get("node") or {}
        if n.get("isAdult") and not mature:
            continue
        novel = n.get("format") == "NOVEL"
        rt = (e.get("relationType") or "").replace("_", " ").capitalize()
        relations.append({
            "id": ln_id(n["id"]) if novel else None,
            "url": None if novel else n.get("siteUrl"),
            "title": (n.get("title") or {}).get("english") or (n.get("title") or {}).get("romaji"),
            "relation": f"{rt} · {FORMATS.get(n.get('format'), (n.get('format') or n.get('type') or '').title())}",
            "year": (n.get("startDate") or {}).get("year"),
            "cover": (n.get("coverImage") or {}).get("medium"),
            "blur": bool(n.get("isAdult")) and not mature,
        })
    relations.sort(key=lambda r: r["id"] is None)   # other light novels first, adaptations after

    title, alt = _title(m)
    cover = m.get("coverImage") or {}
    start, end = _fdate(m.get("startDate")), _fdate(m.get("endDate"))
    return {
        "id": ln_id(m["id"]),
        "url": m.get("siteUrl") or f"https://anilist.co/manga/{m['id']}",
        "title": title,
        "alttitle": alt,
        "aliases": [s for s in m.get("synonyms") or [] if s not in (title, alt)][:8],
        "released": (start or "unknown") + (f" to {end}" if end and end != start else ""),
        "status": STATUS.get(m.get("status"), m.get("status")),
        "volumes": m.get("volumes"),
        "rating": round(m["averageScore"] / 10, 2) if m.get("averageScore") else None,
        "votecount": m.get("popularity") or 0,
        "favourites": m.get("favourites") or 0,
        "staff": list(staff.items()),
        "country": m.get("countryOfOrigin"),
        "description": description(m.get("description")),
        "cover": cover.get("extraLarge") or cover.get("large"),
        "cover_blur": bool(m.get("isAdult")) and not mature,
        "tag_groups": groups,
        "relations": relations,
        "links": [{"label": l["site"], "url": l["url"]} for l in m.get("externalLinks") or []
                  if str(l.get("url", "")).startswith(("http://", "https://"))],
    }
