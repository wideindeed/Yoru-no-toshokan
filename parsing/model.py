"""Data types shared by the parser, query builder and UI."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# kind -> meaning of `value`
#   tag        str tag id
#   tag_any    list[str] tag ids, OR'ed together
#   lang       list[str] language codes, OR'ed
#   platform   list[str] platform codes, OR'ed
#   engine     str exact VNDB engine string (release filter)
#   length     int 1..5            (op: "=")
#   released   list[[op, date]]    (all must hold)
#   rating     int 10..100         (op: ">=")
#   votecount  int                 (op: ">=")
KINDS = {"tag", "tag_any", "lang", "platform", "engine", "length",
         "released", "rating", "votecount", "title"}


@dataclass
class Criterion:
    kind: str
    value: Any
    label: str
    op: str = "="
    exclude: bool = False
    min_level: float | None = None   # per-criterion tag-level override
    phrase: str = ""                 # input phrase it came from
    method: str = ""                 # rule | synonym | exact | fuzzy | embedding
    score: float = 100.0
    id: int = 0                      # position in ParseResult.criteria (for chips)

    def key(self) -> tuple:
        v = self.value
        if isinstance(v, list):
            v = tuple(tuple(x) if isinstance(x, list) else x for x in v)
        return (self.kind, v, self.op, self.exclude)

    @property
    def display(self) -> str:
        return ("NOT: " if self.exclude else "") + self.label

    def to_dict(self) -> dict:
        d = asdict(self)
        d["display"] = self.display
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Criterion":
        d = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        if d.get("kind") not in KINDS:
            raise ValueError(f"unknown criterion kind: {d.get('kind')!r}")
        return cls(**d)


@dataclass
class PhraseReport:
    phrase: str
    criteria: list[Criterion]
    method: str          # how the phrase was resolved ("unmatched" if not)
    score: float = 0.0


@dataclass
class ParseResult:
    text: str
    criteria: list[Criterion] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    report: list[PhraseReport] = field(default_factory=list)

    def add(self, c: Criterion) -> bool:
        if any(c.key() == x.key() for x in self.criteria):
            return False
        c.id = len(self.criteria)
        self.criteria.append(c)
        return True

    def of_kind(self, kind: str) -> list[Criterion]:
        return [c for c in self.criteria if c.kind == kind]

    def tag_ids(self, exclude: bool = False) -> list[str]:
        out = []
        for c in self.criteria:
            if c.exclude != exclude:
                continue
            if c.kind == "tag":
                out.append(c.value)
            elif c.kind == "tag_any":
                out.extend(c.value)
        return out
