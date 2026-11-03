"""Turn a natural-language request into a ParseResult.

Per clause (see rules.split_phrases):
  1. whole-clause synonym ("no sexual content", "female lead heroine")
  2. scoped negation: text after "no / not / without / doesn't have / avoid ..."
     up to the end of the clause is excluded; the part before stays positive.
     A negation that is itself a tag name ("no romance plot") is kept as a tag.
  3. per segment: synonyms.yaml patterns -> rules (engine, dates, language,
     platform, length, quality) -> exact word-window scan -> fuzzy on what is
     left. Stopwords ("I want", "ideally", "it should be") are ignored; any
     other leftover word is reported as not understood, never dropped.
"""
from __future__ import annotations

import copy

from parsing import rules
from parsing.matcher import GENDER_WORDS, ROLE_SUFFIXES, SYNONYMS_PATH, Match, Synonyms, TagMatcher
from parsing.model import ParseResult, PhraseReport
from settings import load_config
from vndb.tags import TagIndex

MAX_WINDOW = 5
#  Words that only make sense attached to another word ("cheerful heroine").
#  They are never looked up alone, and a span containing one does not fall
#  back to role families ("cheerful" -> Cheerful Hero would be wrong).
ROLE_WORDS = GENDER_WORDS | {w for s in ROLE_SUFFIXES for w in s.split()} | {
    "character", "characters", "lead", "mc", "protag", "main"}


class QueryParser:
    def __init__(self, index: TagIndex, cfg: dict | None = None,
                 synonyms_path=SYNONYMS_PATH, embedder=None, log=print, source: str = "vn"):
        self.cfg = cfg or load_config()
        self.index = index
        self.source = source
        self.synonyms = Synonyms.load(index, synonyms_path, log=log, source=source)
        if embedder is None and self.cfg.get("use_embeddings") and source == "vn":
            embedder = _try_load_embedder(index, self.cfg, log)
        self.matcher = TagMatcher(index, self.synonyms, self.cfg, embedder=embedder)

    def parse(self, text: str) -> ParseResult:
        res = ParseResult(text)
        for phrase in rules.split_phrases(text):
            self._parse_phrase(phrase, res)
        return res

    # ------------------------------------------------------------------
    def _apply(self, m: Match, phrase: str, exclude: bool, res: ParseResult) -> list:
        added = []
        for c in m.criteria:
            c.phrase, c.method, c.score = phrase, m.method, m.score
            c.exclude = c.exclude != exclude     # negating an exclude makes it an include
            if res.add(c):
                added.append(c)
        return added

    def _parse_phrase(self, phrase: str, res: ParseResult) -> None:
        # 1. A synonym for the whole clause wins.
        m = self.matcher.lookup_exact(phrase, synonyms_only=True)
        if m:
            added = self._apply(m, phrase, False, res)
            res.report.append(PhraseReport(phrase, added, m.method, m.score))
            return

        acc = _Acc(phrase)
        pos, neg = rules.split_on_negation(phrase)
        if neg is not None:
            # 2. A negation that is a tag name itself ("no romance plot").
            neg_full = phrase[len(pos):]
            m = self.matcher.lookup_exact(neg_full)
            if m and m.method in ("exact", "synonym") and rules.has_negation(m.matched_text):
                acc.extend(self._apply(m, phrase, False, res), m.method, m.score)
                neg = None
        self._segment(pos, False, phrase, res, acc)
        if neg is not None:
            self._segment(neg, True, phrase, res, acc)
        res.report.append(acc.report())

    # ------------------------------------------------------------------
    def _segment(self, text: str, exclude: bool, phrase: str, res: ParseResult, acc: "_Acc") -> None:
        if not text.strip():
            return
        # a. regex paraphrases from synonyms.yaml
        for rx, templates in self.synonyms.patterns:
            hit = rx.search(text)
            if hit:
                m = Match(copy.deepcopy(templates), "pattern", 100.0, hit.group(0))
                acc.extend(self._apply(m, phrase, exclude, res), "pattern", 100.0)
                text = text[: hit.start()] + " " + text[hit.end():]

        # b. structured rules
        ro = rules.extract(text, self.cfg, exclude=exclude)
        for c in ro.criteria:
            c.phrase = phrase
        acc.extend([c for c in ro.criteria if res.add(c)], "rule" if ro.criteria else None, 100.0)

        tokens = rules.tokenize(ro.leftover)
        used = [False] * len(tokens)

        # c. exact multi-word windows, longest first
        for size in range(min(MAX_WINDOW, len(tokens)), 1, -1):
            for i in range(len(tokens) - size + 1):
                if any(used[i:i + size]) or all(rules.is_stop(t) for t in tokens[i:i + size]):
                    continue
                m = self.matcher.lookup_window(" ".join(tokens[i:i + size]))
                if m:
                    acc.extend(self._apply(m, phrase, exclude, res), m.method, m.score)
                    used[i:i + size] = [True] * size

        # d. remaining spans of meaningful words
        for span in _spans(tokens, used):
            words = [tokens[i] for i in span]
            text = " ".join(words)
            m = self.matcher.lookup_window(text) or self.matcher.match(text, embeddings=False)
            if m:
                acc.extend(self._apply(m, phrase, exclude, res), m.method, m.score)
                continue
            # single words of a multi-word span ("dark vampire" -> Vampire)
            left = []
            has_role = any(w in ROLE_WORDS for w in words)
            for w in words:
                m = None if w in ROLE_WORDS else self.matcher.lookup_window(w)
                if m and m.method == "family" and has_role:
                    m = None
                if m:
                    acc.extend(self._apply(m, phrase, exclude, res), m.method, m.score)
                    self._leftover(left, exclude, phrase, res, acc)
                    left = []
                else:
                    left.append(w)
            self._leftover(left, exclude, phrase, res, acc)

    def _leftover(self, words: list[str], exclude: bool, phrase: str, res: ParseResult, acc: "_Acc") -> None:
        """Last resort for unplaced words: optional embedding match, else report them."""
        if not words:
            return
        text = " ".join(words)
        m = self.matcher.lookup_embedding(text)
        if m:
            acc.extend(self._apply(m, phrase, exclude, res), m.method, m.score)
        else:
            acc.unmatched(text, res)


def _spans(tokens: list[str], used: list[bool]) -> list[list[int]]:
    """Runs of consecutive unused, non-stopword token positions."""
    out, cur = [], []
    for i, t in enumerate(tokens):
        if used[i] or rules.is_stop(t):
            if cur:
                out.append(cur)
                cur = []
        else:
            cur.append(i)
    if cur:
        out.append(cur)
    return out


class _Acc:
    """Collects criteria, methods and score for one clause's report line."""

    def __init__(self, phrase: str):
        self.phrase = phrase
        self.added: list = []
        self.methods: list[str] = []
        self.score: float | None = None

    def extend(self, crits: list, method: str | None, score: float) -> None:
        self.added += crits
        if method:
            if method not in self.methods:
                self.methods.append(method)
            self.score = score if self.score is None else min(self.score, score)

    def unmatched(self, text: str, res: ParseResult) -> None:
        res.unmatched.append(text)
        if "unmatched" not in self.methods:
            self.methods.append("unmatched")

    def report(self) -> PhraseReport:
        return PhraseReport(self.phrase, self.added, "+".join(self.methods) or "ignored (filler)",
                            self.score if self.score is not None else 0.0)


def _try_load_embedder(index, cfg, log):
    try:
        from parsing.embed import EmbeddingMatcher
    except ImportError as e:  # module or sentence-transformers missing
        log(f"use_embeddings is on but the embedding matcher is unavailable ({e}); continuing without it")
        return None
    try:
        return EmbeddingMatcher(index, cfg, log=log)
    except Exception as e:  # pragma: no cover - depends on local install
        log(f"Could not start embedding matcher ({e}); continuing without it")
        return None
