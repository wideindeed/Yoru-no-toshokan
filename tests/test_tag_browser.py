from parsing.tag_browser import TagBrowser, plain
from vndb.tags import Tag, TagIndex

IDX = TagIndex.build([
    Tag("g5", "Vampire", [], "cont", True, True, 900, "Elements of [url=https://x]vampire[/url] lore."),
    Tag("g6", "Vampire Heroine", [], "cont", True, True, 300),
    Tag("g7", "Time Loop", ["Groundhog Day"], "cont", True, True, 500, "A period of time repeats itself."),
    Tag("g8", "Nukige", [], "ero", True, True, 800),
])
B = TagBrowser(IDX)


def names(q, **kw):
    return [r["name"] for r in B.search(q, **kw)]


def test_name_alias_description_and_typos():
    assert names("vampire") == ["Vampire", "Vampire Heroine"]
    assert names("groundhog") == ["Time Loop"]
    assert names("repeats") == ["Time Loop"]
    assert names("vampyre")[0] == "Vampire"


def test_ero_filter_and_markup():
    assert names("nukige") == ["Nukige"] and names("nukige", include_ero=False) == []
    assert plain("a [url=https://x]b[/url] [spoiler]c[/spoiler]") == "a b c"
