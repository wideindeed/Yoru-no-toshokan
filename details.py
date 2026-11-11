"""Detail page for one VN: field list, VNDB description markup -> safe HTML, page shaping."""
from __future__ import annotations

import html
import re

from parsing.rules import LENGTH_LABELS
from vndb.labels import LANGUAGE_LABELS, PLATFORM_LABELS, STAFF_ROLE_LABELS

DETAIL_FIELDS = ", ".join([
    "id", "title", "alttitle", "aliases", "released", "rating", "votecount", "length",
    "length_minutes", "length_votes", "description", "languages", "platforms", "olang", "devstatus",
    "image.url", "image.sexual", "image.violence",
    "tags.id", "tags.name", "tags.rating", "tags.spoiler", "tags.category",
    "developers.id", "developers.name",
    "staff.id", "staff.name", "staff.role",
    "screenshots.thumbnail", "screenshots.url", "screenshots.sexual", "screenshots.violence",
    "relations.id", "relations.title", "relations.relation", "relations.released",
    "relations.image.thumbnail", "relations.image.sexual", "relations.image.violence",
    "extlinks.url", "extlinks.label",
])

RELATION_LABELS = {"seq": "Sequel", "preq": "Prequel", "set": "Same setting", "alt": "Alternative version",
                   "char": "Shares characters", "side": "Side story", "par": "Parent story",
                   "ser": "Same series", "fan": "Fandisc", "orig": "Original game"}
TAG_CATEGORIES = [("cont", "Content"), ("tech", "Technical"), ("ero", "Sexual content")]
DEVSTATUS = {1: "In development", 2: "Cancelled"}
ROLE_ORDER = ["scenario", "director", "art", "chardesign", "music", "songs"]


# ------------------------------------------------------------ description
def _link(target: str, text: str) -> str:
    """[url=...] target -> internal VN page, vndb.org, or an external http(s) link. Anything else: plain text."""
    t = html.unescape(target).strip()
    if m := re.fullmatch(r"/?(v\d+)", t):
        return f'<a href="/vn/{m[1]}">{text}</a>'
    if t.startswith("/"):
        t = "https://vndb.org" + t
    if not re.match(r"https?://", t):
        return text
    return f'<a href="{html.escape(t, quote=True)}" target="_blank" rel="noopener">{text}</a>'


def bbcode(text: str | None) -> str:
    """VNDB description markup (https://vndb.org/d9#4) -> HTML. Input is escaped first,
    so only the tags produced here can appear."""
    if not text:
        return ""
    s = html.escape(text, quote=True)
    raws: list[str] = []                     # [raw]/[code] content is kept literally
    s = re.sub(r"\[(raw|code)\](.*?)\[/\1\]", lambda m: raws.append(m[2]) or f"\x00{len(raws) - 1}\x00", s, flags=re.S)
    s = re.sub(r"\[url=([^\]]+)\](.*?)\[/url\]", lambda m: _link(m[1], m[2]), s, flags=re.S | re.I)
    for tag, rep in (("b", "strong"), ("i", "em"), ("u", "u"), ("s", "s")):
        s = re.sub(rf"\[{tag}\](.*?)\[/{tag}\]", rf"<{rep}>\1</{rep}>", s, flags=re.S | re.I)
    s = re.sub(r"\[spoiler\](.*?)\[/spoiler\]", r'<span class="spoiler" role="button" tabindex="0" title="click to reveal">\1</span>', s, flags=re.S | re.I)
    s = re.sub(r"\[quote\](.*?)\[/quote\]", r"<blockquote>\1</blockquote>", s, flags=re.S | re.I)
    # bare VNDB ids like v17 become links to their pages (not inside existing tags/links)
    s = re.sub(r"(?<![\w/=\"#&>])v(\d+)\b(?![^<]*</a>)", r'<a href="/vn/v\1">v\1</a>', s)
    s = s.replace("\n", "<br>")
    return re.sub(r"\x00(\d+)\x00", lambda m: raws[int(m[1])], s)


# ------------------------------------------------------------ page shaping
def _blur(img: dict | None, cfg: dict, mature: bool) -> bool:
    if not img or mature:
        return False
    return (img.get("sexual") or 0) >= cfg["blur_sexual_level"] or (img.get("violence") or 0) >= cfg["blur_violence_level"]


def _length(vn: dict) -> str | None:
    parts = []
    if vn.get("length"):
        parts.append(LENGTH_LABELS.get(vn["length"], ""))
    if vn.get("length_minutes"):
        h, m = divmod(vn["length_minutes"], 60)
        parts.append(f"~{h}h{m:02d}m from {vn.get('length_votes') or 0} votes")
    return " · ".join(p for p in parts if p) or None


def shape(vn: dict, cfg: dict, mature: bool = False) -> dict:
    tags = sorted(vn.get("tags") or [], key=lambda t: -(t.get("rating") or 0))
    groups = []
    for cat, label in TAG_CATEGORIES:
        if cat == "ero" and not mature:
            continue
        items = [{"id": t["id"], "name": t["name"], "rating": round(t.get("rating") or 0, 1),
                  "spoiler": t.get("spoiler") or 0} for t in tags if t.get("category") == cat]
        if items:
            groups.append({"label": label, "tags": items})

    staff_rows = []
    for role in ROLE_ORDER:
        names = list(dict.fromkeys(s["name"] for s in vn.get("staff") or [] if s.get("role") == role))
        if names:
            staff_rows.append((STAFF_ROLE_LABELS.get(role, role), names))

    img = vn.get("image") or {}
    return {
        "id": vn["id"],
        "url": f"https://vndb.org/{vn['id']}",
        "title": vn.get("title"),
        "alttitle": vn.get("alttitle"),
        "aliases": vn.get("aliases") or [],
        "released": vn.get("released") or "unknown",
        "devstatus": DEVSTATUS.get(vn.get("devstatus")),
        "rating": round(vn["rating"] / 10, 2) if vn.get("rating") else None,
        "votecount": vn.get("votecount") or 0,
        "length": _length(vn),
        "developers": [d["name"] for d in vn.get("developers") or []],
        "staff": staff_rows,
        "original_language": LANGUAGE_LABELS.get(vn.get("olang"), vn.get("olang")),
        "languages": [LANGUAGE_LABELS.get(l, l) for l in vn.get("languages") or []],
        "platforms": [PLATFORM_LABELS.get(p, p) for p in vn.get("platforms") or []],
        "description": bbcode(vn.get("description")),
        "cover": img.get("url"),
        "cover_blur": _blur(img, cfg, mature),
        "tag_groups": groups,
        "screenshots": [{"thumb": s.get("thumbnail") or s.get("url"), "url": s.get("url"),
                         "blur": _blur(s, cfg, mature)} for s in vn.get("screenshots") or []],
        "relations": [{"id": r["id"], "title": r.get("title"),
                       "relation": RELATION_LABELS.get(r.get("relation"), r.get("relation")),
                       "year": (r.get("released") or "")[:4] or None,
                       "cover": (r.get("image") or {}).get("thumbnail"),
                       "blur": _blur(r.get("image"), cfg, mature)} for r in vn.get("relations") or []],
        "links": list({l.get("label"): {"label": l.get("label"), "url": l["url"]}
                       for l in reversed(vn.get("extlinks") or [])
                       if str(l.get("url", "")).startswith(("http://", "https://"))}.values())[::-1],
    }
