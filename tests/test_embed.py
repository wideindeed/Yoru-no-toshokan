"""Embedding matcher with a fake model (no download, no GPU)."""
import numpy as np
import pytest

pytest.importorskip("sentence_transformers")

from parsing import embed  # noqa: E402
from vndb.tags import Tag, TagIndex  # noqa: E402


class FakeModel:
    """Bag-of-letters vectors: enough to make 'vampires' closest to 'Vampire'."""
    calls = 0

    def encode(self, texts, **_):
        FakeModel.calls += 1
        out = np.zeros((len(texts), 26), np.float32)
        for r, t in enumerate(texts):
            for ch in t.lower():
                if ch.isalpha() and ch.isascii():
                    out[r, ord(ch) - 97] += 1
        return out / np.linalg.norm(out, axis=1, keepdims=True)


def test_match_and_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(embed, "DATA_DIR", tmp_path)
    monkeypatch.setattr(embed, "EMB_PATH", tmp_path / "e.npy")
    monkeypatch.setattr(embed, "META_PATH", tmp_path / "e.json")
    idx = TagIndex.build([Tag("g5", "Vampire", [], "cont", True, True, 1),
                          Tag("g7", "Horror", [], "cont", True, True, 1)])
    m = embed.EmbeddingMatcher(idx, {}, log=lambda *_: None, model=FakeModel())
    assert m.match("vampires")[0][0] == "g5"
    before = FakeModel.calls
    embed.EmbeddingMatcher(idx, {}, log=lambda *_: None, model=FakeModel())
    assert FakeModel.calls == before                  # second start loads the cached vectors
