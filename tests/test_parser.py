"""Parser tests (plan §7). Uses the real data/tags.json if present (no network)."""
import pytest

from parsing.matcher import Synonyms, _gender_compatible, singular
from parsing.parser import QueryParser
from parsing.rules import split_phrases
from settings import load_config
from vndb.tags import TAGS_PATH, Tag, TagIndex, read_tags

pytestmark = pytest.mark.skipif(
    not TAGS_PATH.exists(),
    reason="data/tags.json missing; run `python cli.py --refresh-tags` once",
)


@pytest.fixture(scope="module")
def parser():
    _, tags = read_tags()
    return QueryParser(TagIndex.build(tags), load_config(), log=lambda *_: None)


def crit(res, kind, exclude=False):
    return [c for c in res.criteria if c.kind == kind and c.exclude == exclude]


def tag_ids(res, exclude=False):
    return set(res.tag_ids(exclude=exclude))


# ---- the five inputs from plan §7 ---------------------------------------
def test_example_query(parser):
    r = parser.parse("fantasy setting, english, RPG Maker, multiple endings, female lead heroine")
    assert tag_ids(r) == {"g2", "g148", "g134"}       # Fantasy, Multiple Endings, Female Protagonist
    assert crit(r, "lang")[0].value == ["en"]
    assert crit(r, "engine")[0].value == "RPG Maker"
    assert r.unmatched == []


def test_short_no_horror_android_after_2018(parser):
    r = parser.parse("short, no horror, android, after 2018")
    assert crit(r, "length")[0].value == 2
    assert tag_ids(r, exclude=True) == {"g7"}           # NOT Horror
    assert tag_ids(r) == set()
    assert crit(r, "platform")[0].value == ["and"]
    assert crit(r, "released")[0].value == [[">=", "2019-01-01"]]
    assert r.unmatched == []


def test_rpgm_mz_male_protagonist(parser):
    r = parser.parse("rpgm mz games with a male protagonist")
    assert crit(r, "engine")[0].value == "RPG Maker"   # versions are not distinguished on VNDB
    assert tag_ids(r) == {"g133"}
    assert r.unmatched == []


def test_highly_rated_mystery_time_loops(parser):
    r = parser.parse("highly rated mystery with time loops")
    rating = crit(r, "rating")[0]
    assert (rating.op, rating.value) == (">=", 70)
    assert tag_ids(r) == {"g19", "g349"}               # Mystery, Time Loop
    assert r.unmatched == []


def test_typos_recovered_by_fuzzy(parser):
    r = parser.parse("typo test: fantsy, multipul endings")
    assert tag_ids(r) == {"g2", "g148"}
    assert {c.method for c in r.criteria} == {"fuzzy"}
    assert all(c.score >= 85 for c in r.criteria)
    assert r.unmatched == ["typo test"]                # reported, never silently dropped


# ---- extra coverage -------------------------------------------------------
def test_full_example_with_content_level(parser):
    r = parser.parse("fantasy setting, suggestive themes, english, RPG Maker, "
                     "multiple endings, female lead heroine")
    any_ = crit(r, "tag_any")
    assert len(any_) == 1 and "g1274" in any_[0].value and any_[0].label == "Content: suggestive"


def test_content_levels_and_negation(parser):
    r = parser.parse("no sexual content")
    assert tag_ids(r) == {"g235"}                      # all_ages level -> "No Sexual Content" tag
    r = parser.parse("without fanservice")
    assert crit(r, "tag_any", exclude=True)            # negated suggestive bundle
    r = parser.parse("no romance plot")                # a tag whose own name starts with "No"
    assert tag_ids(r) == {"g2223"}


def test_dates(parser):
    v = lambda q: crit(parser.parse(q), "released")[0].value
    assert v("2018-2022") == [[">=", "2018-01-01"], ["<", "2023-01-01"]]
    assert v("between 2010 and 2015") == [[">=", "2010-01-01"], ["<", "2016-01-01"]]
    assert v("before 2010") == [["<", "2010-01-01"]]
    assert v("since 2015") == [[">=", "2015-01-01"]]
    assert v("in 2020") == [[">=", "2020-01-01"], ["<", "2021-01-01"]]
    assert v("90s") == [[">=", "1990-01-01"], ["<", "2000-01-01"]]


def test_language_negation_and_platform_dedupe(parser):
    r = parser.parse("not japanese, windows/pc")
    assert crit(r, "lang", exclude=True)[0].value == ["ja"]
    assert [c.value for c in crit(r, "platform")] == [["win"]]
    assert r.unmatched == []


def test_length_word_inside_tag_phrase_is_not_length(parser):
    r = parser.parse("long hair")
    assert not crit(r, "length")
    assert r.unmatched == ["long hair"]                # no such VN tag on VNDB


def test_fuzzy_guards_reject_lookalikes(parser):
    # VNDB has no "Cheerful Heroine"; neighbours that only share "heroine"
    # or differ in gender must not be accepted.
    for q in ("cheerful heroine", "genki heroine"):
        r = parser.parse(q)
        assert r.criteria == [] and r.unmatched == [q], (q, [c.label for c in r.criteria])


def test_gender_guard(parser):
    assert _gender_compatible("cheerful hero", "cheerful hero")
    assert not _gender_compatible("cheerful heroine", "cheerful hero")


def test_engine_variants(parser):
    for q, name in [("renpy", "Ren'Py"), ("made in wolf rpg", "Wolf RPG Editor"),
                    ("tyranobuilder", "TyranoScript"), ("kirikiri", "KiriKiri")]:
        assert crit(parser.parse(q), "engine")[0].value == name, q


def test_report_covers_every_phrase(parser):
    r = parser.parse("fantasy, gibberishword, english")
    assert [p.phrase for p in r.report] == ["fantasy", "gibberishword", "english"]
    assert r.report[1].method == "unmatched"


def test_split_and_singular():
    assert split_phrases("a, b; c and d\ne with f") == ["a", "b", "c", "d", "e", "f"]
    assert singular("time loops") == "time loop"
    assert singular("mysteries") == "mystery"


def test_synonym_loader_warns_on_missing_tag(tmp_path):
    p = tmp_path / "syn.yaml"
    p.write_text("phrases:\n  foo: { tag: 'Nonexistent Tag' }\n  bar: { tag: 'Fantasy' }\n",
                 encoding="utf-8")
    idx = TagIndex.build([Tag("g2", "Fantasy", [], "cont", True, True, 1)])
    s = Synonyms.load(idx, p, log=lambda *_: None)
    assert "bar" in s and "foo" not in s
    assert any("Nonexistent Tag" in w for w in s.warnings)


def test_shipped_synonyms_all_resolve(parser):
    assert parser.synonyms.warnings == []


# ---- M2.5: conversational input ------------------------------------------
def test_conversational_endings_heroine_maids(parser):
    r = parser.parse("I want a game involvings multiple endings, with a strong heroine, some maids")
    assert {c.value for c in crit(r, "tag")} == {"g148", "g1869"}  # Multiple Endings, Strong Female Protagonist
    maids = crit(r, "tag_any")
    assert len(maids) == 1 and {"g112", "g993", "g1191"} <= set(maids[0].value)
    assert r.unmatched == []


def test_conversational_girl_fantasy_english(parser):
    r = parser.parse("Looking for something where the main character is a girl, "
                     "set in a fantasy world, and it should be in English please")
    assert tag_ids(r) == {"g134", "g2"}              # Female Protagonist, Fantasy
    assert crit(r, "lang")[0].value == ["en"]
    assert r.unmatched == []                         # no chips for "it should be", "please"


def test_conversational_vampires_rpgm_no_horror(parser):
    r = parser.parse("I would love a dark story about vampires that was made in RPG Maker "
                     "but has no horror elements, ideally released after 2015")
    assert tag_ids(r) == {"g5"}                      # Vampire
    assert tag_ids(r, exclude=True) == {"g7"}        # NOT Horror (was included before M2.5)
    assert crit(r, "engine")[0].value == "RPG Maker"
    assert crit(r, "released")[0].value == [[">=", "2016-01-01"]]
    assert r.unmatched == ["dark"]                   # no VNDB tag; reported, not guessed


def test_scoped_negation(parser):
    r = parser.parse("I don't want any horror or gore")
    assert len(tag_ids(r, exclude=True)) == 2 and tag_ids(r) == set()
    r = parser.parse("fantasy that doesn't have sexual content")
    assert tag_ids(r) == {"g2"} and tag_ids(r, exclude=True) == {"g23"}
    r = parser.parse("a kinetic novel with no romance plot")
    assert "g2223" in tag_ids(r)                     # negation that is itself a tag name


def test_not_too_is_degree_not_negation(parser):
    r = parser.parse("not too long")
    c = crit(r, "length")[0]
    assert (c.op, c.value, c.exclude) == ("<=", 3, False)


def test_patterns_and_stopwords(parser):
    assert tag_ids(parser.parse("playing as a guy")) == {"g133"}
    assert tag_ids(parser.parse("the protagonist should be a woman")) == {"g134"}
    r = parser.parse("ideally, please, I would like something")
    assert r.criteria == [] and r.unmatched == []
