"""Local web UI: python app.py -> http://127.0.0.1:<port from config.yaml, default 5050>"""
from __future__ import annotations

import re

from flask import Flask, abort, jsonify, render_template, request

from finder import SOURCES, Finder
from parsing.model import Criterion
from parsing.tag_browser import TagBrowser
from vndb.client import VNDBError

app = Flask(__name__)
finder: Finder | None = None
API_NAME = {"vn": "VNDB", "ln": "AniList"}


def get_finder() -> Finder:
    global finder
    if finder is None:
        finder = Finder()
    return finder


def source_of(body: dict | None = None) -> str:
    s = (body or {}).get("source") or request.args.get("source") or "vn"
    return s if s in SOURCES else "vn"


@app.get("/")
def index():
    f = get_finder()
    return render_template("index.html", use_llm=bool(f.cfg.get("use_llm")),
                           default_sort=f.cfg["default_sort"])


@app.post("/api/parse")
def api_parse():
    body = request.get_json(force=True)
    try:
        res, rewritten, note = get_finder().interpret(body.get("text", ""), use_llm=bool(body.get("use_llm")),
                                                      source=source_of(body))
    except VNDBError as e:   # first LN use downloads the AniList tag list
        return jsonify({"error": f"{API_NAME[source_of(body)]} API error: {e}"}), 502
    return jsonify({
        "criteria": [c.to_dict() for c in res.criteria],
        "unmatched": res.unmatched, "unmatched_role": res.unmatched_role,
        "rewritten": rewritten,
        "note": note,
        "report": [{"phrase": r.phrase, "method": r.method, "score": r.score,
                    "got": [c.display for c in r.criteria]} for r in res.report],
    })


@app.post("/api/search")
def api_search():
    body = request.get_json(force=True)
    source = source_of(body)
    try:
        crits = [Criterion.from_dict(d) for d in body.get("criteria", [])]
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"bad criteria: {e}"}), 400
    try:
        out = get_finder().search(crits, sort=body.get("sort"), mode=body.get("mode", "all"),
                                  page=int(body.get("page", 1)), mature=bool(body.get("mature")),
                                  skip_excludes=set(body.get("skip_excludes") or []), source=source)
    except VNDBError as e:
        return jsonify({"error": f"{API_NAME[source]} API error: {e}"}), 502
    return jsonify({"cards": out.cards, "more": out.more, "page": out.page,
                    "notes": out.notes, "filters": out.filters})


@app.get("/api/tags")
def api_tags():
    """Tag browser: ?q=text, &mature=1 to include sexual-content tags, &source=ln for AniList tags."""
    side = get_finder().side(source_of())
    if side.browser is None:
        side.browser = TagBrowser(side.index, side.parser.synonyms)
    return jsonify(side.browser.search(request.args.get("q", "")[:100], include_ero=request.args.get("mature") == "1"))


@app.get("/api/prefs")
def api_prefs():
    return jsonify(get_finder().prefs.to_dict())


@app.post("/api/prefs")
def api_prefs_change():
    """{action: exclude|unexclude|hide|unhide, layer, name|id, title, source}"""
    f, body = get_finder(), request.get_json(force=True)
    act, layer, source = body.get("action"), body.get("layer", "normal"), source_of(body)
    if act == "exclude":
        tags = f.resolve_tags(str(body.get("name", "")).strip(), source=source)
        if not tags:
            return jsonify({"error": f"no {API_NAME[source]} tag matches {body.get('name')!r}"}), 400
        for t in tags:
            f.prefs.add_exclude(layer, t.id, t.name)
    elif act == "unexclude":
        f.prefs.remove_exclude(layer, body.get("id"))
    elif act == "hide" and re.fullmatch(r"[vl]\d{1,9}", str(body.get("id"))):
        f.prefs.hide(body["id"], body.get("title", ""))
    elif act == "unhide":
        f.prefs.unhide(body.get("id"))
    else:
        return jsonify({"error": "bad action"}), 400
    return jsonify(f.prefs.to_dict())


@app.get("/about")
def about():
    return render_template("about.html")


@app.get("/vn/<vid>")
def vn_page(vid: str):
    if not re.fullmatch(r"v\d{1,7}", vid):
        abort(404)
    mature = request.args.get("mature") == "1"
    try:
        vn = get_finder().details(vid, mature=mature)
    except VNDBError as e:
        return f"VNDB API error: {e}", 502
    if vn is None:
        abort(404)
    return render_template("vn.html", vn=vn, mature=mature)


@app.get("/ln/<lid>")
def ln_page(lid: str):
    if not re.fullmatch(r"l\d{1,9}", lid):
        abort(404)
    mature = request.args.get("mature") == "1"
    try:
        ln = get_finder().ln_details(lid, mature=mature)
    except VNDBError as e:
        return f"AniList API error: {e}", 502
    if ln is None:
        abort(404)
    return render_template("ln.html", ln=ln, mature=mature)


if __name__ == "__main__":
    f = get_finder()   # load tags (and download them on first run) before serving
    port = int(f.cfg.get("port", 5050))
    print(f"Yoru no Toshokan: http://127.0.0.1:{port}")
    # single-threaded: the API client throttles requests and is not built for concurrency
    app.run(host="127.0.0.1", port=port, debug=False, threaded=False)
