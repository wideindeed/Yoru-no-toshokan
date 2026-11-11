"""tests/golden_queries.yaml: sentences the parser must keep understanding the same way."""
from pathlib import Path

import pytest
import yaml

from parsing.parser import QueryParser
from settings import load_config
from vndb.tags import TAGS_PATH, TagIndex, read_tags

pytestmark = pytest.mark.skipif(not TAGS_PATH.exists(), reason="data/tags.json missing")
CASES = yaml.safe_load((Path(__file__).parent / "golden_queries.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def parser():
    return QueryParser(TagIndex.build(read_tags()[1]), load_config(), log=lambda *_: None)


@pytest.mark.parametrize("case", CASES, ids=[c["q"] for c in CASES])
def test_golden(parser, case):
    res = parser.parse(case["q"])
    assert [c.display for c in res.criteria] == case["got"]
    assert res.unmatched == case.get("unmatched", [])
