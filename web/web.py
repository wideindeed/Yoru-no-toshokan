"""Browser bridge (runs in Pyodide): the same parser, query builder and detail shaping
as the desktop app. JavaScript does the VNDB requests; every function here takes and
returns JSON strings.

The web version is all-ages only: Mature is always off, and positive requests for
sexual-content tags are dropped with a note.
"""
from __future__ import annotations

import json

import details
import like
import query_builder as qb
from parsing.model import Criterion
from parsing.parser import QueryParser
from parsing.tag_browser import TagBrowser
from settings import load_config
from vndb.tags import TagIndex, read_tags

MAX_EXCLUDES, MAX_HIDDEN = 50, 300
ADULT_NOTE = "Adult content isn't available on the web version, so that part of your search was skipped."

cfg = load_config()
cfg["use_llm"] = cfg["use_embeddings"] = False
_, _tags = read_tags()
index = TagIndex.build(_tags)
parser = QueryParser(index, cfg, log=lambda *a: None)
browser = TagBrowser(index, parser.synonyms)
FIELDS = {"vn": qb.VN_FIELDS, "detail": details.DETAIL_FIELDS}


def _ids(c: Criterion) -> list[str]:
    return [c.value] if c.kind == "tag" else c.value if c.kind == "tag_any" else []


def _adult(c: Criterion) -> bool:
    """A positive criterion that asks for sexual content (any tag in VNDB's 'ero' category)."""
    return not c.exclude and (c.label.lower() == "content: explicit" or any(
        (t := index.tags.get(i)) is not None and t.category == "ero" for i in _ids(c)))


def _crits(criteria_json: str) -> list[Criterion]:
    return [c for c in (Criterion.from_dict(d) for d in json.loads(criteria_json)) if not _adult(c)]


def parse(text: str) -> str:
    res = parser.parse(text)
    keep = [c for c in res.criteria if not _adult(c)]
    return json.dumps({
        "criteria": [c.to_dict() for c in keep],
        "unmatched": res.unmatched, "unmatched_role": res.unmatched_role,
        "notes": [ADULT_NOTE] if len(keep) < len(res.criteria) else [],
        "report": [{"phrase": r.phrase, "method": r.method, "score": r.score,
                    "got": [c.display for c in r.criteria]} for r in res.report],
    })


def query(criteria_json: str, sort: str, mode: str, page: int, excludes_json: str, hidden_json: str) -> str:
    """Request body for POST /kana/vn. excludes: [{id, name}], hidden: [vid]."""
    crits, hidden = _with_prefs(criteria_json, excludes_json, hidden_json)
    return json.dumps(_body(crits, sort, mode, page, hidden))


def relaxed(criteria_json: str, sort: str, excludes_json: str, hidden_json: str) -> str:
    """Close matches when an all-tags search found too little: levels of request bodies
    (all tags but one, then two, ...; see qb.relaxed). {"need": per page, "levels": [[body]]}"""
    crits, hidden = _with_prefs(criteria_json, excludes_json, hidden_json)
    return json.dumps({"need": int(cfg["results_per_page"]),
                       "levels": [[_body(cs, sort, "all", 1, hidden) for cs in lv] for lv in qb.relaxed(crits)]})


def close_cards(results_json: str, criteria_json: str, sort: str, limit: int, n_all: int) -> str:
    groups = qb.wanted_tag_groups(_crits(criteria_json))
    close = qb.rank_close([qb.to_card(v, cfg, groups, False) for v in json.loads(results_json)], sort, int(limit))
    return json.dumps({"cards": close, "note": qb.close_note(int(n_all)) if close else ""})


def _with_prefs(criteria_json, excludes_json, hidden_json):
    crits = _crits(criteria_json)
    crits += [Criterion("tag", t["id"], t["name"], exclude=True)
              for t in json.loads(excludes_json)[:MAX_EXCLUDES]]
    hidden = [v for v in json.loads(hidden_json)[:MAX_HIDDEN] if isinstance(v, str) and v.startswith("v")]
    return crits, hidden


def _body(crits, sort, mode, page, hidden) -> dict:
    # mature_filter(False) is added unconditionally: the query can't switch it off here
    filters = qb._and([qb.build_filters(crits, cfg, mode=mode), qb.mature_filter(False, cfg),
                       *[["id", "!=", v] for v in hidden]])
    sort = sort if sort in qb.SORTS else cfg["default_sort"]
    field, reverse = qb.api_sort(sort)
    return {"filters": filters, "fields": qb.VN_FIELDS, "sort": field,
            "reverse": reverse, "results": int(cfg["results_per_page"]), "page": int(page)}


def cards(results_json: str, criteria_json: str, mode: str) -> str:
    groups = qb.wanted_tag_groups(_crits(criteria_json))
    out = [qb.to_card(v, cfg, groups, False) for v in json.loads(results_json)]
    if mode == "any" and groups:
        out.sort(key=lambda c: -c["hits"])
    return json.dumps(out)


def detail(vn_json: str) -> str:
    d = details.shape(json.loads(vn_json), cfg, mature=False)
    d["description"] = d["description"].replace('href="/vn/', 'href="#')   # in-page links
    return json.dumps(d)


def resolve(name: str) -> str:
    """Tag name / alias / nickname / typo -> [{id, name}] for the always-exclude list."""
    name = name.strip()
    t = index.by_name(name) or index.lookup(name)
    if t:
        return json.dumps([{"id": t.id, "name": t.name}])
    m = parser.matcher.match(name, embeddings=False)
    ids = [i for c in (m.criteria if m else []) for i in _ids(c)]
    return json.dumps([{"id": i, "name": index.tags[i].name} for i in ids if i in index.tags])


def tags(q: str) -> str:
    """Tag browser results (all-ages: sexual-content tags are left out)."""
    return json.dumps(browser.search(q, include_ero=False))


# ------------------------------------------------------------------ light novels (AniList)
# Loaded on first use. Same all-ages rules: adult tags/genres dropped, isAdult:false always,
# and an adult title opened by id is refused.
_ln: dict = {}


def _ln_side():
    if not _ln:
        from anilist.tags import TAGS_PATH
        _, tags_ = read_tags(TAGS_PATH)
        _ln["index"] = TagIndex.build(tags_)
        _ln["parser"] = QueryParser(_ln["index"], cfg, log=lambda *a: None, source="ln")
        _ln["browser"] = TagBrowser(_ln["index"], _ln["parser"].synonyms)
    return _ln


def _ln_adult(c: Criterion) -> bool:
    idx = _ln_side()["index"]
    return not c.exclude and (c.label.lower() == "content: explicit" or c.label.lower() == "content: suggestive"
                              or any((t := idx.tags.get(i)) is not None and t.category == "ero" for i in _ids(c)))


def _ln_crits(criteria_json: str) -> list[Criterion]:
    return [c for c in (Criterion.from_dict(d) for d in json.loads(criteria_json)) if not _ln_adult(c)]


def ln_parse(text: str) -> str:
    res = _ln_side()["parser"].parse(text)
    keep = [c for c in res.criteria if not _ln_adult(c)]
    return json.dumps({
        "criteria": [c.to_dict() for c in keep],
        "unmatched": res.unmatched, "unmatched_role": res.unmatched_role,
        "notes": [ADULT_NOTE] if len(keep) < len(res.criteria) else [],
        "report": [{"phrase": r.phrase, "method": r.method, "score": r.score,
                    "got": [c.display for c in r.criteria]} for r in res.report],
    })


def ln_query(criteria_json: str, sort: str, mode: str, page: int, excludes_json: str, hidden_json: str) -> str:
    """-> {query: GraphQL text, notes}. Mature is always off, so isAdult:false is always set."""
    from anilist import query as aq
    crits = _ln_crits(criteria_json)
    crits += [Criterion("tag", t["id"], t["name"], exclude=True)
              for t in json.loads(excludes_json)[:MAX_EXCLUDES]]
    hidden = [v for v in json.loads(hidden_json)[:MAX_HIDDEN] if isinstance(v, str)]
    q, notes = aq.build(crits, _ln_side()["index"], cfg, mode=mode, mature=False, page=int(page),
                        sort=sort, hidden=hidden)
    assert "isAdult: false" in q
    return json.dumps({"query": q, "notes": notes})


def ln_cards(data_json: str, criteria_json: str, mode: str, sort: str) -> str:
    from anilist import query as aq
    media, more = aq.merge(json.loads(data_json), sort)
    groups = qb.wanted_tag_groups(_ln_crits(criteria_json))
    out = [aq.to_card(m, cfg, groups, False) for m in media if not m.get("isAdult")]
    if mode == "any" and groups:
        out.sort(key=lambda c: -c["hits"])
    return json.dumps({"cards": out, "more": more})


def ln_detail_query(lid: str) -> str:
    from anilist import query as aq
    mid = aq.media_id(lid)
    return json.dumps(aq.detail_query(mid) if mid is not None else None)


def ln_detail(media_json: str) -> str:
    from anilist import query as aq
    m = json.loads(media_json)
    if m.get("isAdult"):
        return json.dumps({"adult": True})
    return json.dumps(aq.shape(m, cfg, mature=False))


def ln_resolve(name: str) -> str:
    side, name = _ln_side(), name.strip()
    t = side["index"].by_name(name) or side["index"].lookup(name)
    if t:
        return json.dumps([{"id": t.id, "name": t.name}])
    m = side["parser"].matcher.match(name, embeddings=False)
    ids = [i for c in (m.criteria if m else []) for i in _ids(c)]
    return json.dumps([{"id": i, "name": side["index"].tags[i].name} for i in ids if i in side["index"].tags])


def ln_tags(q: str) -> str:
    return json.dumps(_ln_side()["browser"].search(q, include_ero=False))


# ------------------------------------------------------------------ more like this / your VNDB list
def _like_side(source: str):
    return (_ln_side()["index"], _ln_side()["parser"].matcher) if source == "ln" else (index, parser.matcher)


def like_request(source: str, item_id: str, search: str) -> str:
    """The request that fetches one title's tags, by id or by name.
    -> {"vn": /kana/vn body} or {"ln": GraphQL text}"""
    if source == "ln":
        return json.dumps({"ln": like.ln_request(item_id or None, search or None)})
    return json.dumps({"vn": like.vn_request(item_id or None, search or None)})


def like_criteria(source: str, response_json: str, target: str) -> str:
    """The response to like_request -> {"criteria": [...], "title": str|None} for the target library."""
    r = json.loads(response_json) or {}
    found = (like.from_ln(r.get("Media")) if source == "ln"
             else like.from_vn(like.best_vn(r.get("results") or [])))
    if found and source == "ln" and (r.get("Media") or {}).get("isAdult"):
        found = None                       # all ages: no starting from an adult title
    crits = like.like_criteria(found, source, _like_side(source)[0], target, _like_side(target))
    return json.dumps({"criteria": [c.to_dict() for c in crits], "title": found[1] if found else None})


def user_url(name: str) -> str:
    return json.dumps(like.user_url(cfg["api_url"], name))


def user_id(response_json: str) -> str:
    who = like.user_id(json.loads(response_json), "")
    return json.dumps(list(who) if who else None)


def ulist_request(uid: str, page: int) -> str:
    return json.dumps(like.ulist_request(uid, int(page)))


def read_list(rows_json: str) -> str:
    return json.dumps(like.read_list(json.loads(rows_json), index))
