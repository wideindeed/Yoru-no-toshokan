"""Optional semantic tag matcher (all-MiniLM-L6-v2), enabled by use_embeddings: true.

Embeddings of "tag name; aliases" are computed once and cached in
data/tag_embeddings.npy (rebuilt automatically when the tag list changes).
Uses CUDA when available, otherwise CPU.
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

    def match(self, text: str, top_k: int = 1) -> list[tuple[str, float]]:
        """[(tag_id, cosine similarity)], best first."""
        q = self._encode([text])[0]
        sims = self.vectors @ q
        best = np.argsort(-sims)[:top_k]
        return [(self.ids[i], float(sims[i])) for i in best]
