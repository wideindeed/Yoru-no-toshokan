"""Light novel mode: AniList query building and shaping (offline)."""
from anilist import query as aq
from parsing.model import Criterion
from vndb.tags import Tag, TagIndex

CFG = {"results_per_page": 24, "ln_min_tag_rank": 50}


def _tag(id, name, category):
    return Tag(id=id, name=name, aliases=[], category=category, searchable=True, applicable=True, vn_count=0)


def _index():
    return TagIndex.build([_tag("t1", "Isekai", "cont"), _tag("t2", "Villainess", "cont"),
                           _tag("t3", "Female Harem", "cont"), _tag("genre:Romance", "Romance", "genre"),
                           _tag("genre:Hentai", "Hentai", "ero")])


def test_build_all_mode():
    idx = _index()
    crits = [Criterion("tag", "t1", "Isekai"), Criterion("tag", "genre:Romance", "Romance"),
             Criterion("tag", "t3", "Female Harem", exclude=True),
             Criterion("released", [[">=", "2016-01-01"]], "after 2015"),
             Criterion("lang", "en", "English")]
    q, notes = aq.build(crits, idx, CFG, hidden=["l5", "v9"])
    assert q.count("Page(") == 1
    for part in ('tag_in: ["Isekai"]', 'genre_in: ["Romance"]', 'tag_not_in: ["Female Harem"]',
                 "startDate_greater: 20159999", "isAdult: false", "id_not_in: [5]", "minimumTagRank: 50"):
        assert part in q, part
    assert notes and "English" in notes[0]


def test_any_mode_splits_and_adult_overrides():
    idx = _index()
    crits = [Criterion("tag_any", ["t1", "t2"], "isekai or villainess")]
    q, _ = aq.build(crits, idx, CFG)
    assert q.count("Page(") == 2 and "q1:" in q
    q, _ = aq.build([Criterion("tag", "genre:Hentai", "Hentai")], idx, CFG)
    assert "isAdult: false" not in q                       # asking for adult content overrides Mature off


def test_merge_and_card():
    m = {"id": 7, "title": {"romaji": "Ookami", "english": "Spice and Wolf"}, "startDate": {"year": 2006},
         "averageScore": 82, "popularity": 900, "isAdult": False, "coverImage": {"medium": "c.jpg"},
         "genres": ["Romance"], "tags": [{"id": 1, "name": "Isekai", "rank": 60}],
         "staff": {"edges": [{"role": "Story", "node": {"name": {"full": "Isuna Hasekura"}}}]}}
    media, more = aq.merge({"q0": {"pageInfo": {"hasNextPage": False}, "media": [m]},
                            "q1": {"pageInfo": {"hasNextPage": True}, "media": [m]}})
    assert len(media) == 1 and more
    c = aq.to_card(media[0], CFG)
    assert c["id"] == "l7" and c["rating"] == 8.2 and c["developers"] == ["Isuna Hasekura"]
    assert c["title"] == "Spice and Wolf" and c["alttitle"] == "Ookami"


def test_description_is_safe():
    out = aq.description('<script>x</script><br>ok <i>it</i> ~!twist!~')
    assert "<script>" not in out and "<br>" in out and "<i>it</i>" in out and 'class="spoiler"' in out
