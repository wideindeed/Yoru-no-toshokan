"""Optional semantic tag matcher (all-MiniLM-L6-v2), enabled by use_embeddings: true.

Embeddings of "tag name; aliases" are computed once and cached in
data/tag_embeddings.npy (rebuilt automatically when the tag list changes).
Uses CUDA when available, otherwise CPU.

    python -m parsing.embed     # (re)write static/vectors/ for the "close in meaning"
                                # suggestions in the tag browser (desktop and web)
"""
from __future__ import annotations

import hashlib
import json

import numpy as np

from settings import DATA_DIR

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMB_PATH = DATA_DIR / "tag_embeddings.npy"
META_PATH = DATA_DIR / "tag_embeddings.json"


def _tag_text(t) -> str:
    return "; ".join([t.name, *t.aliases[:5]])


class EmbeddingMatcher:
    def __init__(self, index, cfg: dict, log=print, model=None):
        from sentence_transformers import SentenceTransformer   # lazy: optional dependency
        import torch
        self.index = index
        self.ids = sorted(index.tags)
        if model is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model = SentenceTransformer(MODEL_NAME, device=device)
            log(f"Embedding matcher: {MODEL_NAME} on {device}")
        self.model = model
        self.vectors = self._load_or_build(log)

    def _encode(self, texts: list[str]) -> np.ndarray:
        v = self.model.encode(texts, batch_size=128, convert_to_numpy=True, normalize_embeddings=True)
        return v.astype(np.float32)

    def _load_or_build(self, log) -> np.ndarray:
        texts = [_tag_text(self.index.tags[i]) for i in self.ids]
        digest = hashlib.sha256(json.dumps([MODEL_NAME, self.ids, texts]).encode()).hexdigest()
        if EMB_PATH.exists() and META_PATH.exists():
            try:
                if json.loads(META_PATH.read_text())["digest"] == digest:
                    return np.load(EMB_PATH)
            except (ValueError, KeyError, OSError):
                pass
        log(f"Building tag embeddings for {len(texts)} tags (one-time)...")
        vecs = self._encode(texts)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        np.save(EMB_PATH, vecs)
        META_PATH.write_text(json.dumps({"digest": digest, "model": MODEL_NAME}))
        return vecs

    def export_for_browser(self, stem) -> None:
        """Tag vectors for static/related.js, which suggests tags close in meaning in the
        browser with the same model (transformers.js). <stem>.bin is int8 rows (vector * 127),
        <stem>.json lists [id, name, category, count] per row."""
        keep = [i for i, tid in enumerate(self.ids)
                if self.index.tags[tid].searchable and "(obsolete)" not in self.index.tags[tid].name]
        stem.parent.mkdir(parents=True, exist_ok=True)
        np.round(self.vectors[keep] * 127).astype(np.int8).tofile(stem.with_suffix(".bin"))
        rows = [[t.id, t.name, t.category, t.vn_count] for t in (self.index.tags[self.ids[i]] for i in keep)]
        stem.with_suffix(".json").write_text(json.dumps(
            {"model": MODEL_NAME, "dim": int(self.vectors.shape[1]), "tags": rows}, ensure_ascii=False,
            separators=(",", ":")), encoding="utf-8")

    def match(self, text: str, top_k: int = 1) -> list[tuple[str, float]]:
        """[(tag_id, cosine similarity)], best first."""
        q = self._encode([text])[0]
        sims = self.vectors @ q
        best = np.argsort(-sims)[:top_k]
        return [(self.ids[i], float(sims[i])) for i in best]


if __name__ == "__main__":
    from anilist import tags as al_tags
    from settings import ROOT, load_config
    from vndb.tags import load_tag_index
    cfg = load_config()
    vn = EmbeddingMatcher(load_tag_index(), cfg)
    vn.export_for_browser(ROOT / "static" / "vectors" / "vn")
    # AniList tags get their own vectors; they aren't cached in data/ (small, quick to encode)
    ln = EmbeddingMatcher.__new__(EmbeddingMatcher)
    ln.index, ln.model = al_tags.load_tag_index(), vn.model
    ln.ids = sorted(ln.index.tags)
    ln.vectors = ln._encode([_tag_text(ln.index.tags[i]) for i in ln.ids])
    ln.export_for_browser(ROOT / "static" / "vectors" / "ln")
    print("wrote static/vectors/vn.* and ln.*")
