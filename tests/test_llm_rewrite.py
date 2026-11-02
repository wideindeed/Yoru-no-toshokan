"""LLM rewriter with a mocked Ollama (no network)."""
import ast
import json

import pytest
import requests

from parsing.llm_rewrite import LLMRewriter
from parsing.parser import QueryParser
from settings import load_config
from vndb.tags import TAGS_PATH, TagIndex, read_tags

pytestmark = pytest.mark.skipif(not TAGS_PATH.exists(), reason="data/tags.json missing")


class FakeOllama:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append(json)
        reply = self.replies.pop(0)
        if callable(reply):
            reply = reply(json)
        if isinstance(reply, Exception):
            raise reply

        class R:
            def raise_for_status(self): pass
            def json(self, _c=reply): return {"message": {"content": _c}}
        return R()


@pytest.fixture(scope="module")
def parser():
    _, tags = read_tags()
    return QueryParser(TagIndex.build(tags), load_config(), log=lambda *_: None)


def test_rewrite_then_parse(parser):
    fake = FakeOllama([json.dumps({"keywords": ["vampire", "RPG Maker", "no horror", "after 2015"]})])
    rw = LLMRewriter({**load_config(), "llm_repair": True}, parser, session=fake, log=lambda *_: None)
    out = rw.rewrite("I would love a story about vampires made in RPG Maker without horror, after 2015")
    assert out.text == "vampire, RPG Maker, no horror, after 2015"
    assert len(fake.calls) == 1                         # nothing unmatched -> no repair round
    assert fake.calls[0]["options"]["temperature"] == 0
    r = parser.parse(out.text)
    assert set(r.tag_ids()) == {"g5"} and set(r.tag_ids(exclude=True)) == {"g7"}


def test_repair_only_accepts_offered_candidates(parser):
    def pick(req):   # choose the first offered candidate for phrase 1, a fake tag for phrase 2
        lines = req["messages"][0]["content"].splitlines()
        first = ast.literal_eval(lines[-2].split(": ", 1)[1])[0]
        return json.dumps({"choices": [{"phrase": "zorblax qwerty", "tag": first},
                                       {"phrase": "made-up thing", "tag": "Invented Tag"}]})
    fake = FakeOllama([json.dumps({"keywords": ["zorblax qwerty", "made-up thing"]}), pick])
    rw = LLMRewriter(load_config(), parser, session=fake, log=lambda *_: None)
    first, second = rw.rewrite("x").text.split(", ")
    assert parser.index.by_name(first) is not None      # replaced by a real, offered tag
    assert second == "made-up thing"                    # invented tag rejected


@pytest.mark.parametrize("reply", [requests.ConnectionError("down"), "not json", json.dumps({"x": 1})])
def test_falls_back_on_failure(parser, reply):
    rw = LLMRewriter(load_config(), parser, session=FakeOllama([reply]), log=lambda *_: None)
    assert rw.rewrite("fantasy").text is None             # caller parses the original text
