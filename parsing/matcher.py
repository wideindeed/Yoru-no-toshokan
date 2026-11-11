"""Map free-text phrases to VNDB tags (and synonym targets).

Order per phrase, stopping at the first confident hit:
  1. synonyms.yaml (exact, case-insensitive)
  2. exact tag name / alias
  3. rapidfuzz token_set_ratio >= fuzzy_threshold (guarded by token_sort_ratio)
  4. optional embedding matcher (parsing/embed.py)
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from rapidfuzz import fuzz, process

from parsing.model import Criterion
from parsing.rules import LANG_LABELS, singular, strip_filler  # noqa: F401 (singular re-exported)
from vndb.tags import TagIndex

SYNONYMS_PATH = Path(__file__).resolve().parent / "synonyms.yaml"


# ------------------------------------------------------------------ synonyms
class Synonyms:
    """phrase (lowercase) -> list of Criterion templates."""

    def __init__(self, entries: dict[str, list[Criterion]], warnings: list[str],
                 patterns: list[tuple[re.Pattern, list[Criterion]]] | None = None,
                 traits: dict[str, str] | None = None):
        self.entries = entries
        self.warnings = warnings
        self.patterns = patterns or []      # (compiled regex, criterion templates)
        self.traits = traits or {}          # everyday word -> trait in VNDB's words ("nerdy" -> "otaku")

    def get(self, phrase: str) -> list[Criterion] | None:
        return self.entries.get(phrase.strip().lower())

    def __contains__(self, phrase: str) -> bool:
        return phrase.strip().lower() in self.entries

    @classmethod
    def load(cls, index: TagIndex, path: Path | str = SYNONYMS_PATH, log=print,
             source: str = "vn") -> "Synonyms":
        """source "ln" (AniList): an entry's `ln:` block replaces its targets, and names
        AniList doesn't have are skipped quietly (most entries are written for VNDB)."""
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        ln = source == "ln"
        levels = raw.get("content_levels") or {}
        warnings: list[str] = []
        warned: set[str] = set()

        def resolve(name: str, where: str):
            t = index.by_name(name) or index.lookup(name)
            if t is None and name not in warned:
                warned.add(name)
                warnings.append(f"synonyms.yaml: tag {name!r} (used by {where!r}) not found on "
                                f"{'AniList' if ln else 'VNDB'}; skipped")
            return t

        def as_list(v):
            if v is None:
                return []
            return v if isinstance(v, list) else [v]

        def build(key: str, e: dict) -> list[Criterion]:
            out: list[Criterion] = []
            lvl = e.get("min_level")
            for name in as_list(e.get("tag")):
                t = resolve(name, key)
                if t:
                    out.append(Criterion("tag", t.id, t.name, min_level=lvl))
            if e.get("any_tags"):
                ts = [t for n in as_list(e["any_tags"]) if (t := resolve(n, key))]
                if ts:
                    out.append(Criterion("tag_any", [t.id for t in ts],
                                         " / ".join(t.name for t in ts), min_level=lvl))
            for name in as_list(e.get("exclude_tags")):
                t = resolve(name, key)
                if t:
                    out.append(Criterion("tag", t.id, t.name, exclude=True, min_level=lvl))
            if e.get("engine"):
                out.append(Criterion("engine", e["engine"], f"Engine: {e['engine']}"))
            if e.get("lang"):
                codes = as_list(e["lang"])
                out.append(Criterion("lang", codes, " / ".join(LANG_LABELS.get(c, c) for c in codes)))
            if e.get("platform"):
                codes = as_list(e["platform"])
                out.append(Criterion("platform", codes, "Platform: " + " / ".join(codes)))
            if e.get("content"):
                name = e["content"]
                spec = levels.get(name)
                if ln and spec is not None:
                    spec = spec.get("ln", spec)
                if spec is None:
                    warnings.append(f"synonyms.yaml: content level {name!r} (used by {key!r}) is not defined")
                else:
                    pretty = name.replace("_", " ")
                    sub = build(key, {"tag": spec.get("all"),
                                      "exclude_tags": spec.get("exclude_tags"),
                                      "min_level": spec.get("min_level", lvl)})
                    if spec.get("any"):
                        ts = [t for n in as_list(spec["any"]) if (t := resolve(n, key))]
                        if ts:
                            sub.append(Criterion("tag_any", [t.id for t in ts], f"Content: {pretty}",
                                                 min_level=spec.get("min_level", lvl)))
                    out.extend(sub)
            return out

        entries = {}
        for key, e in (raw.get("phrases") or {}).items():
            key = str(key).strip().lower()
            if isinstance(e, str):
                e = {"tag": e}
            if not ln and isinstance(e, dict) and set(e) == {"ln"}:
                continue                    # light-novel-only entry
            if ln and isinstance(e, dict) and "ln" in e:
                e = e["ln"] if isinstance(e["ln"], dict) else {"tag": e["ln"]}
            n_warn = len(warnings)
            crits = build(key, e or {})
            if crits:
                entries[key] = crits
            elif len(warnings) == n_warn:   # nothing explained why it is empty
                warnings.append(f"synonyms.yaml: entry {key!r} has no usable target; skipped")

        # extra generated phrasings: VNDB only, hand-written entries win
        gen = Path(path).with_name("synonyms.generated.yaml")
        if not ln and gen.exists():
            for key, name in ((yaml.safe_load(gen.read_text(encoding="utf-8")) or {}).get("phrases") or {}).items():
                key = str(key).strip().lower()
                t = index.by_name(name)
                if key not in entries and t is not None:
                    entries[key] = [Criterion("tag", t.id, t.name)]

        patterns = []
        for i, e in enumerate(raw.get("patterns") or []):
            src = (e or {}).get("pattern")
            where = f"patterns[{i}]"
            if not src:
                warnings.append(f"synonyms.yaml: {where} has no 'pattern'; skipped")
                continue
            try:
                rx = re.compile(r"(?<![\w'])(?:" + src + r")(?![\w'])", re.I)
            except re.error as err:
                warnings.append(f"synonyms.yaml: {where} bad regex {src!r}: {err}; skipped")
                continue
            crits = build(where, {k: v for k, v in e.items() if k != "pattern"})
            if crits:
                patterns.append((rx, crits))

        if ln:
            if warnings:
                log(f"AniList: {len(warnings)} synonyms.yaml targets don't apply to light novels (normal)")
        else:
            for w in warnings:
                log("WARNING: " + w)
        traits = {str(k).strip().lower(): str(v).strip().lower() for k, v in (raw.get("traits") or {}).items()}
        return cls(entries, warnings, patterns, traits)


# ------------------------------------------------------------------ matcher
#  VNDB splits many tags by gender ("Cheerful Hero" vs "Cheerful Heroine"),
#  which are only a few characters apart. A fuzzy hit must keep every
#  gendered word of the query.
GENDER_WORDS = {"hero", "heroine", "heroines", "heroes", "male", "female", "boy", "boys",
                "girl", "girls", "man", "men", "woman", "women", "brother", "sister",
                "father", "mother", "son", "daughter", "husband", "wife"}


def _gender_compatible(query: str, text: str) -> bool:
    q = set(re.findall(r"[a-z]+", query.lower())) & GENDER_WORDS
    return q <= set(re.findall(r"[a-z]+", text.lower()))


#  Role suffixes used to group tags into families (longest first).
ROLE_SUFFIXES = ["support characters", "support character", "love interests", "love interest",
                 "protagonists", "protagonist", "antagonists", "antagonist",
                 "heroines", "heroine", "heroes", "hero"]


#  Who a description is about. VNDB names character traits per role: "Short Heroine",
#  "Heroine with Glasses", "Otaku Protagonist", "Protagonist's Kouhai as a Heroine".
ROLES = ("heroine", "hero", "protagonist")
ROLE_OF = {**dict.fromkeys("girl girls heroine heroines she woman women lady waifu girlfriend".split(), "heroine"),
           **dict.fromkeys("guy guys boy boys hero heroes he man men husbando boyfriend".split(), "hero"),
           **dict.fromkeys("protagonist protagonists mc protag".split(), "protagonist")}
_ROLE_NAME_RES = [re.compile(r"^protagonist's (?P<base>.+) as an? (?P<role>heroine|hero)$"),
                  re.compile(r"^(?P<role>heroine|hero|protagonist) with (?P<base>.+)$"),
                  re.compile(r"^(?P<base>.+) (?P<role>heroine|hero|protagonist)$")]


#  A shared long word inflates whole-string scores: "cheerful heroine" vs
#  "cook heroine" scores ~86. So the words that differ between the query and
#  the candidate must themselves look like a typo of each other.
MIN_DIFF_WORD_RATIO = 75


def _differing_words_similar(query: str, text: str) -> bool:
    q = set(re.findall(r"\w+", query.lower()))
    t = set(re.findall(r"\w+", text.lower()))
    dq, dt = q - t, t - q
    if not dq or not dt:
        return True          # pure subset/superset: already guarded by token_sort_ratio
    return fuzz.ratio(" ".join(sorted(dq)), " ".join(sorted(dt))) >= MIN_DIFF_WORD_RATIO


def candidates(phrase: str) -> list[str]:
    base = re.sub(r"\s+", " ", phrase.strip().lower())
    stripped = strip_filler(base)
    out = []
    for c in (base, stripped, singular(base), singular(stripped)):
        if c and c not in out:
            out.append(c)
    return out


@dataclass
class Match:
    criteria: list[Criterion]   # templates; caller fills phrase/exclude
    method: str
    score: float
    matched_text: str = ""


class TagMatcher:
    def __init__(self, index: TagIndex, synonyms: Synonyms, cfg: dict, embedder=None):
        self.index = index
        self.syn = synonyms
        self.threshold = float(cfg["fuzzy_threshold"])
        self.min_sort = float(cfg.get("fuzzy_min_sort_ratio", 80))
        self.embedder = embedder
        self.emb_threshold = float(cfg.get("embedding_threshold", 0.55))
        # fuzzy choice list: every tag name/alias + every synonym key
        self._texts: list[str] = []
        self._targets: list[tuple[str, str]] = []   # ("tag", id) | ("syn", key)
        for text, ids in index.by_text.items():
            self._texts.append(text)
            self._targets.append(("tag", ids[0]))
        for key in synonyms.entries:
            self._texts.append(key)
            self._targets.append(("syn", key))
        # role families: "maid" -> Maid Heroine / Maid Protagonist / Maid Support Character
        self.families: dict[str, list[str]] = {}
        for t in index.tags.values():
            name = t.name.lower()
            for suf in ROLE_SUFFIXES:
                if name.endswith(" " + suf):
                    base = name[: -len(suf) - 1].strip()
                    if len(base) >= 3 and base not in ("multiple", "main", "central", "major", "minor"):
                        self.families.setdefault(base, []).append(t.id)
                    break
        for ids in self.families.values():
            ids.sort(key=lambda i: -index.tags[i].vn_count)
        # role traits: ("heroine", "short") -> Short Heroine, ("heroine", "glasses") -> Heroine with Glasses
        self.roles: dict[tuple[str, str], str] = {}
        for t in sorted(index.tags.values(), key=lambda t: t.vn_count):     # most popular wins
            if not t.searchable:
                continue
            name = re.sub(r"\s*\(.*?\)$", "", t.name.lower())    # "(non-loli)"
            for rx in _ROLE_NAME_RES:
                if m := rx.match(name):
                    self.roles[(m["role"], m["base"])] = t.id
                    break

    def _tag_crit(self, tag_id: str) -> list[Criterion]:
        t = self.index.tags[tag_id]
        return [Criterion("tag", t.id, t.name)]

    def _popularity(self, target) -> int:
        kind, ref = target
        if kind == "tag":
            return self.index.tags[ref].vn_count
        ids = [c.value for c in self.syn.entries[ref] if c.kind == "tag"]
        return max((self.index.tags[i].vn_count for i in ids), default=0)

    def lookup_exact(self, phrase: str, synonyms_only: bool = False) -> Match | None:
        cands = candidates(phrase)
        for c in cands:
            hit = self.syn.get(c)
            if hit:
                return Match(copy.deepcopy(hit), "synonym", 100.0, c)
        if synonyms_only:
            return None
        for c in cands:
            t = self.index.lookup(c)
            if t:
                return Match(self._tag_crit(t.id), "exact", 100.0, c)
        return None

    def lookup_window(self, text: str) -> Match | None:
        """Exact-only lookup for a word window inside a longer sentence:
        synonym key, tag name/alias, then role family. No fuzzy here."""
        base = text.strip().lower()
        cands = [base] if singular(base) == base else [base, singular(base)]
        for c in cands:
            hit = self.syn.get(c)
            if hit:
                return Match(copy.deepcopy(hit), "synonym", 100.0, c)
        for c in cands:
            t = self.index.lookup(c)
            if t:
                return Match(self._tag_crit(t.id), "exact", 100.0, c)
        for c in cands + [self.syn.traits[c] for c in cands if c in self.syn.traits]:
            ids = self.families.get(c)
            if ids:
                if len(ids) == 1:
                    return Match(self._tag_crit(ids[0]), "family", 100.0, c)
                tags = [self.index.tags[i] for i in ids]
                roles = [t.name[len(c) + 1:] for t in tags]
                label = f"{tags[0].name[:len(c)]}: " + " / ".join(roles)
                return Match([Criterion("tag_any", ids, label)], "family", 100.0, c)
        return None

    def lookup_role(self, text: str, role: str) -> Match | None:
        """A trait of the person being described: ("short", "heroine") -> Short Heroine."""
        base = text.strip().lower()
        if base not in self.syn.traits and singular(base) != base and singular(base) in self.families:
            return None     # "some maids" are maid characters, not the heroine's job
        for c in dict.fromkeys([base, singular(base)]):
            for key in (c, self.syn.traits.get(c)):
                if key and (tid := self.roles.get((role, key))):
                    return Match(self._tag_crit(tid), "role", 100.0, c)
        return None

    def lookup_fuzzy(self, phrase: str) -> Match | None:
        best = None
        for c in candidates(phrase):
            if len(c) < 3:
                continue
            for text, score, i in process.extract(
                c, self._texts, scorer=fuzz.token_set_ratio,
                score_cutoff=self.threshold, limit=25,
            ):
                sort_score = fuzz.token_sort_ratio(c, text)
                if " " not in c and fuzz.ratio(singular(re.sub(r"\W", "", c)),
                                               singular(re.sub(r"\W", "", text))) < 90:
                    continue    # one word must look like a typo ("vampir"), not another word ("even"/"elven")
                if (sort_score < self.min_sort or not _gender_compatible(c, text)
                        or not _differing_words_similar(c, text)):
                    continue
                target = self._targets[i]
                rank = (score, sort_score, self._popularity(target))
                if best is None or rank > best[0]:
                    best = (rank, target, text)
        if best is None:
            return None
        (score, _, _), (kind, ref), text = best
        crits = self._tag_crit(ref) if kind == "tag" else copy.deepcopy(self.syn.entries[ref])
        return Match(crits, "fuzzy", round(score, 1), text)

    def lookup_embedding(self, phrase: str) -> Match | None:
        if self.embedder is None:
            return None
        text = strip_filler(phrase) or phrase
        hits = self.embedder.match(text, top_k=1)
        if hits and hits[0][1] >= self.emb_threshold:
            tag_id, sim = hits[0]
            return Match(self._tag_crit(tag_id), "embedding", round(sim * 100, 1),
                         self.index.tags[tag_id].name)
        return None

    def match(self, phrase: str, embeddings: bool = True) -> Match | None:
        return (self.lookup_exact(phrase)
                or self.lookup_fuzzy(phrase)
                or (self.lookup_embedding(phrase) if embeddings else None))
