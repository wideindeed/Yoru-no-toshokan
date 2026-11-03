"""Tag browser: find VNDB tags by name, alias, nickname or description, typo-tolerant.
Pure Python (difflib), so the browser version can run it in Pyodide."""
from __future__ import annotations

import difflib
import re

from vndb.tags import TagIndex

_MARKUP = re.compile(r"\[/?[a-z]+(?:=[^\]]*)?\]", re.I)
_WORD = re.compile(r"[a-z0-9']+")


def plain(desc: str) -> str:
    """VNDB description markup -> plain text."""
    return re.sub(r"\s+", " ", _MARKUP.sub("", desc or "")).strip()


class TagBrowser:
    def __init__(self, index: TagIndex, synonyms=None):
        self.index = index
        self.synonyms = synonyms          # parsing.matcher.Synonyms, for nicknames ("female mc")
        self.texts: dict[str, list[tuple[str, str]]] = {}   # tag id -> [(lowercase text, original)]
        self.words: dict[str, set[str]] = {}                # word of a name/alias -> tag ids
        self.desc: dict[str, str] = {}
        for t in index.tags.values():
            self.texts[t.id] = [(x.lower(), x) for x in [t.name, *t.aliases] if x.strip()]
            self.desc[t.id] = plain(t.description).lower()
            for low, _ in self.texts[t.id]:
                for w in _WORD.findall(low):
                    if len(w) >= 3:
                        self.words.setdefault(w, set()).add(t.id)
        self._vocab = list(self.words)

    def search(self, query: str, limit: int = 30, include_ero: bool = True) -> list[dict]:
        q = " ".join(query.lower().split())
        if len(q) < 2:
            return []
        qwords = _WORD.findall(q)
        at_word = re.compile(r"\b" + re.escape(q))
        in_desc = [re.compile(r"\b" + re.escape(w)) for w in qwords]
        best: dict[str, tuple[float, str]] = {}   # id -> (score, why)

        def hit(tid: str, score: float, why: str):
            if score > best.get(tid, (0, ""))[0]:
                best[tid] = (score, why)

        for c in (self.synonyms.get(q) or []) if self.synonyms else []:
            for tid in [c.value] if c.kind == "tag" else c.value if c.kind == "tag_any" else []:
                hit(tid, 100, f'nickname "{q}"')

        for tid, texts in self.texts.items():
            for i, (low, orig) in enumerate(texts):
                why = "" if i == 0 else f"also called {orig}"
                if low == q:
                    hit(tid, 100 - (i > 0), why)
                elif low.startswith(q):
                    hit(tid, 90 - (i > 0), why)
                elif re.search(r"\b" + re.escape(q), low):
                    hit(tid, 80 - (i > 0), why)
            if qwords and all(re.search(r"\b" + re.escape(w), self.desc[tid]) for w in qwords):
                hit(tid, 50, "in description")

        # typos: every query word close to some word of a name/alias ("vampyre" -> Vampire)
        if len(q) >= 4 and len(best) < limit:
            per_word = []
            for w in qwords:
                close = difflib.get_close_matches(w, self._vocab, n=8, cutoff=0.8) if len(w) >= 4 else [w]
                per_word.append(set().union(*(self.words.get(c, set()) for c in close)))
            for tid in set.intersection(*per_word) if per_word else set():
                hit(tid, 60, "close spelling")

        if not best and len(qwords) > 1:   # nothing for the whole phrase: try each word
            return [r for w in qwords for r in self.search(w, limit // len(qwords), include_ero)][:limit]

        tags = self.index.tags
        rows = [(s, why, tags[tid]) for tid, (s, why) in best.items()
                if include_ero or tags[tid].category != "ero"]
        rows.sort(key=lambda r: (-r[0], -r[2].vn_count))
        return [{"id": t.id, "name": t.name, "category": t.category, "vn_count": t.vn_count,
                 "why": why, "description": _snippet(plain(t.description), qwords)}
                for _, why, t in rows[:limit]]


def _snippet(text: str, qwords: list[str], width: int = 160) -> str:
    """A short piece of the description, around the first query word if it appears."""
    if len(text) <= width:
        return text
    low = text.lower()
    pos = min((p for w in qwords if (p := low.find(w)) >= 0), default=0)
    start = max(0, pos - width // 3) if pos > width // 2 else 0
    return ("..." if start else "") + text[start:start + width].rstrip() + "..."
