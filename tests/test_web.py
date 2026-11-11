"""web/web.py (the Pyodide bridge), run here with the pure-Python rapidfuzz stand-in."""
import json
import sys
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web"


@pytest.fixture(scope="module")
def web():
    pytest.importorskip("vndb.tags").read_tags()   # needs data/tags.json
    saved = {k: sys.modules.pop(k) for k in list(sys.modules) if k.split(".")[0] in ("rapidfuzz", "parsing")}
    sys.path.insert(0, str(WEB))
    try:
        import web as w
        assert Path(sys.modules["rapidfuzz"].__file__).parent.parent == WEB   # the shim, not the wheel
        yield w
    finally:
        sys.path.remove(str(WEB))
        for k in [k for k in sys.modules if k.split(".")[0] in ("rapidfuzz", "parsing", "web")]:
            del sys.modules[k]
        sys.modules.update(saved)


def test_parse_and_query(web):
    p = json.loads(web.parse("vampires, made in RPG Maker, no horror, after 2015"))
    assert [c["display"] for c in p["criteria"]] == ["Vampire", "Engine: RPG Maker", "NOT: Horror", "Released 2016 or later"]
    q = json.loads(web.query(json.dumps(p["criteria"]), "rating", "all", 1, "[]", '["v17"]'))
    assert ["tag", "!=", ["g23", 2, 0.0]] in q["filters"] and ["id", "!=", "v17"] in q["filters"]


def test_adult_requests_are_dropped(web):
    p = json.loads(web.parse("explicit fantasy"))
    assert [c["display"] for c in p["criteria"]] == ["Fantasy"] and p["notes"]
    q = json.loads(web.query(json.dumps([{"kind": "tag", "value": "g23", "label": "Sexual Content"}]), "rating", "all", 1, "[]", "[]"))
    assert q["filters"] == ["tag", "!=", ["g23", 2, 0.0]]


def test_light_novels_stay_all_ages(web):
    pytest.importorskip("anilist.tags").TAGS_PATH.exists() or pytest.skip("needs data/anilist_tags.json")
    p = json.loads(web.ln_parse("hentai, isekai villainess"))
    assert [c["display"] for c in p["criteria"]] == ["Isekai", "Villainess"] and p["notes"]
    q = json.loads(web.ln_query(json.dumps(p["criteria"]), "rating", "all", 1, "[]", '["l5", "v17"]'))
    assert "isAdult: false" in q["query"] and "id_not_in: [5]" in q["query"]
    assert json.loads(web.ln_detail('{"id": 1, "isAdult": true}')) == {"adult": True}
    assert all(t["category"] != "ero" for t in json.loads(web.ln_tags("breasts")))


def test_like_and_list(web):
    good = [t for t in web.index.tags.values() if t.category == "cont" and 500 < (t.vn_count or 0) < 3000][:3]
    tags = [{"id": t.id, "rating": 2.8, "spoiler": 0} for t in good]
    resp = {"results": [{"id": "v17", "title": "Ever17", "votecount": 900, "tags": tags}]}
    r = json.loads(web.like_criteria("vn", json.dumps(resp), "vn"))
    assert r["title"] == "Ever17" and {c["value"] for c in r["criteria"] if c["kind"] == "tag"} == {t.id for t in good}
    assert {"kind": "id", "value": "v17"}.items() <= next(c for c in r["criteria"] if c["kind"] == "id").items()
    assert json.loads(web.like_criteria("vn", '{"results": []}', "vn"))["criteria"] == []
    assert json.loads(web.user_id('{"yorhel": {"id": "u2", "username": "Yorhel"}}')) == ["u2", "Yorhel"]
    assert json.loads(web.user_id('{"nobody": null}')) is None
    rows = [{"id": "v17", "vote": 90, "labels": [{"id": 2}], "vn": {"tags": tags}},
            {"id": "v5", "vote": None, "labels": [{"id": 5}], "vn": {"tags": tags}}]   # wishlist: not seen
    lst = json.loads(web.read_list(json.dumps(rows)))
    assert lst["items"] == {"v17": 90} and lst["taste"]
