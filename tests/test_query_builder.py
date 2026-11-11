"""Snapshot of the generated filter JSON (plan §7)."""
import query_builder as qb
from parsing.model import Criterion
from settings import load_config

CFG = load_config()


def test_filter_snapshot():
    crits = [
        Criterion("tag", "g2", "Fantasy"),
        Criterion("tag_any", ["g1274", "g236"], "Content: suggestive"),
        Criterion("tag", "g7", "Horror", exclude=True),
        Criterion("lang", ["en"], "English"),
        Criterion("engine", "RPG Maker", "Engine: RPG Maker"),
        Criterion("released", [[">=", "2016-01-01"]], "Released 2016 or later"),
        Criterion("length", 3, "Length: Medium or shorter", op="<="),
    ]
    assert qb.build_filters(crits, CFG) == [
        "and",
        ["tag", "=", ["g2", 0, 1.2]],
        ["or", ["tag", "=", ["g1274", 0, 1.2]], ["tag", "=", ["g236", 0, 1.2]]],
        ["tag", "!=", ["g7", 2, 0.0]],
        ["lang", "=", "en"],
        ["release", "=", ["engine", "=", "RPG Maker"]],
        ["released", ">=", "2016-01-01"],
        ["length", "<=", 3],
    ]
    # match-any: positive tags OR'ed, everything else still required
    anyf = qb.build_filters(crits, CFG, mode="any")
    assert anyf[1][0] == "or" and ["tag", "!=", ["g7", 2, 0.0]] in anyf


def test_card_blur_and_tags():
    vn = {"id": "v1", "title": "X", "released": "2020-05-01", "rating": 75.5,
          "image": {"url": "u", "thumbnail": "t", "sexual": 1.5, "violence": 0},
          "tags": [{"id": "g2", "name": "Fantasy", "rating": 2.5, "spoiler": 0, "category": "cont"},
                   {"id": "g9", "name": "Twist", "rating": 3, "spoiler": 2, "category": "cont"},
                   {"id": "g23", "name": "Sexual Content", "rating": 3, "spoiler": 0, "category": "ero"}]}
    card = qb.to_card(vn, CFG)
    assert card["tags"] == ["Fantasy"] and card["blur"] and card["year"] == "2020"
    assert "Sexual Content" in qb.to_card(vn, CFG, show_explicit=True)["tags"]


def test_mature_filter():
    from parsing.model import Criterion
    crits = [Criterion("tag", "g2", "Fantasy")]
    assert qb.build_filters(crits, CFG, mature=False)[-1] == ["tag", "!=", ["g23", 2, 0.0]]
    assert qb.build_filters(crits, CFG, mature=True)[-1][:2] == ["tag", "="]
    # a content level written in the query wins over the toggle
    own = crits + [Criterion("tag_any", ["g23", "g5"], "Content: explicit")]
    assert qb.mature_filter(False, CFG) not in qb.build_filters(own, CFG, mature=False)


def test_description_markup_is_safe():
    import details
    out = details.bbcode('<script>x</script> [url=javascript:alert(1)]bad[/url] [url=/v17]ok[/url] '
                         '[spoiler]twist[/spoiler] see v5')
    assert "<script>" not in out and "javascript" not in out
    assert '<a href="/vn/v17">ok</a>' in out and 'class="spoiler"' in out and 'href="/vn/v5"' in out


def test_prefs_roundtrip(tmp_path):
    from prefs import Prefs
    p = Prefs(tmp_path / "p.json")
    p.add_exclude("normal", "g542", "Otome Game")
    p.add_exclude("normal", "g542", "Otome Game")      # no duplicates
    p.hide("v1", "X")
    q = Prefs(tmp_path / "p.json")
    assert q.exclude["normal"] == [{"id": "g542", "name": "Otome Game"}] and q.hidden == {"v1": "X"}
    q.remove_exclude("normal", "g542"); q.unhide("v1")
    assert Prefs(tmp_path / "p.json").to_dict() == {"exclude": {l: [] for l in ("normal", "mature", "ln_normal", "ln_mature")}, "hidden": [], "vndb_list": None}
