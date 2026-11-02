"""Local web UI: python app.py -> http://127.0.0.1:<port from config.yaml, default 5050>"""
from __future__ import annotations

import re

from flask import Flask, abort, jsonify, render_template, request

from finder import Finder
from parsing.model import Criterion
from vndb.client import VNDBError

app = Flask(__name__)
finder: Finder | None = None


def get_finder() -> Finder:
    global finder
    if finder is None:
        finder = Finder()
    return finder


@app.get("/")
def index():
    f = get_finder()
    return render_template("index.html", use_llm=bool(f.cfg.get("use_llm")),
                           default_sort=f.cfg["default_sort"])


@app.post("/api/parse")
def api_parse():
    body = request.get_json(force=True)
    res, rewritten, note = get_finder().interpret(body.get("text", ""), use_llm=bool(body.get("use_llm")))
    return jsonify({
        "criteria": [c.to_dict() for c in res.criteria],
        "unmatched": res.unmatched,
        "rewritten": rewritten,
        "note": note,
        "report": [{"phrase": r.phrase, "method": r.method, "score": r.score,
                    "got": [c.display for c in r.criteria]} for r in res.report],
    })


@app.post("/api/search")
def api_search():
    body = request.get_json(force=True)
    try:
        crits = [Criterion.from_dict(d) for d in body.get("criteria", [])]
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"bad criteria: {e}"}), 400
    try:
        out = get_finder().search(crits, sort=body.get("sort"), mode=body.get("mode", "all"),
                                  page=int(body.get("page", 1)), mature=bool(body.get("mature")),
                                  skip_excludes=set(body.get("skip_excludes") or []))
    except VNDBError as e:
        return jsonify({"error": f"VNDB API error: {e}"}), 502
    return jsonify({"cards": out.cards, "more": out.more, "page": out.page,
                    "notes": out.notes, "filters": out.filters})


@app.get("/api/prefs")
def api_prefs():
    return jsonify(get_finder().prefs.to_dict())


@app.post("/api/prefs")
def api_prefs_change():
    """{action: exclude|unexclude|hide|unhide, layer, name|id, title}"""
    f, body = get_finder(), request.get_json(force=True)
    act, layer = body.get("action"), body.get("layer", "normal")
    if act == "exclude":
        tags = f.resolve_tags(str(body.get("name", "")).strip())
        if not tags:
            return jsonify({"error": f"no VNDB tag matches {body.get('name')!r}"}), 400
        for t in tags:
            f.prefs.add_exclude(layer, t.id, t.name)
    elif act == "unexclude":
        f.prefs.remove_exclude(layer, body.get("id"))
    elif act == "hide" and re.fullmatch(r"v\d{1,7}", str(body.get("id"))):
        f.prefs.hide(body["id"], body.get("title", ""))
    elif act == "unhide":
        f.prefs.unhide(body.get("id"))
    else:
        return jsonify({"error": "bad action"}), 400
    return jsonify(f.prefs.to_dict())


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


if __name__ == "__main__":
    f = get_finder()   # load tags (and download them on first run) before serving
    port = int(f.cfg.get("port", 5050))
    print(f"Yoru no Toshokan: http://127.0.0.1:{port}")
    # single-threaded: the API client throttles requests and is not built for concurrency
    app.run(host="127.0.0.1", port=port, debug=False, threaded=False)
