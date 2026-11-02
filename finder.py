"""Glue shared by cli.py and app.py: text -> (rewrite) -> parse -> query -> cards."""
from __future__ import annotations

from dataclasses import dataclass, field

import details
from prefs import Prefs
import query_builder as qb
from parsing.model import Criterion, ParseResult
from parsing.parser import QueryParser
from settings import load_config
from vndb.client import VNDBClient
from vndb.tags import load_tag_index


@dataclass
class SearchResult:
    cards: list[dict]
    more: bool
    filters: object
    page: int
    sort: str
    mode: str
    notes: list[str] = field(default_factory=list)


class Finder:
    def __init__(self, cfg: dict | None = None, refresh_tags: bool = False, log=print):
        self.cfg = cfg or load_config()
        self.log = log
        self.client = VNDBClient(self.cfg)
        self.index = load_tag_index(self.client, refresh=refresh_tags, config=self.cfg, log=log)
        self.parser = QueryParser(self.index, self.cfg, log=log)
        self.prefs = Prefs()
        self.rewriter = None
        if self.cfg.get("use_llm"):
            from parsing.llm_rewrite import LLMRewriter
            self.rewriter = LLMRewriter(self.cfg, self.parser, log=log)

    # ---------------------------------------------------------------- parse
    def interpret(self, text: str, use_llm: bool | None = None) -> tuple[ParseResult, str | None, str]:
        """Returns (parse result, rewritten text or None, note about the LLM)."""
        use_llm = self.rewriter is not None if use_llm is None else use_llm
        if use_llm and self.rewriter is None:
            from parsing.llm_rewrite import LLMRewriter
            self.rewriter = LLMRewriter(self.cfg, self.parser, log=self.log)
        if use_llm:
            rw = self.rewriter.rewrite(text)
            if rw.text is not None:
                return self.parser.parse(rw.text), rw.text, rw.note
            return self.parser.parse(text), None, rw.note
        return self.parser.parse(text), None, ""

    # --------------------------------------------------------------- search
    def search(self, criteria: list[Criterion], sort: str | None = None, mode: str = "all",
               page: int = 1, mature: bool = False, results: int | None = None,
               skip_excludes=(), use_prefs: bool = True) -> SearchResult:
        """skip_excludes: always-excluded tag ids dropped for this search only."""
        sort = sort if sort in qb.SORTS else self.cfg["default_sort"]
        n = int(results or self.cfg["results_per_page"])
        crits = list(criteria)
        if use_prefs:
            crits += [Criterion("tag", t["id"], t["name"], exclude=True)
                      for t in self.prefs.exclude[self.prefs.layer(mature)] if t["id"] not in skip_excludes]
        filters = qb.build_filters(crits, self.cfg, mode=mode, mature=mature)
        if use_prefs and self.prefs.hidden:   # "not interested" VNs never come back
            filters = qb._and([filters, *[["id", "!=", v] for v in self.prefs.hidden]])
        data = self.client.query("vn", filters=filters, fields=qb.VN_FIELDS, sort=sort,
                                 reverse=sort != "title", results=n, page=page)
        groups = qb.wanted_tag_groups(criteria)
        cards = [qb.to_card(v, self.cfg, groups, mature) for v in data.get("results", [])]
        if mode == "any" and groups:
            cards.sort(key=lambda c: -c["hits"])   # stable: keeps API order within a hit count
        notes = []
        if not criteria:
            notes.append("No criteria understood; showing top VNDB results.")
        if qb.content_in_query(criteria):
            notes.append("Your content words override the Mature toggle.")
        return SearchResult(cards, bool(data.get("more")), filters, page, sort, mode, notes)

    # -------------------------------------------------------------- details
    def details(self, vid: str, mature: bool = False) -> dict | None:
        """One VN for the detail page (one cached API call)."""
        data = self.client.query("vn", filters=["id", "=", vid], fields=details.DETAIL_FIELDS, results=1)
        rows = data.get("results") or []
        return details.shape(rows[0], self.cfg, mature) if rows else None

    # ---------------------------------------------------------------- prefs
    def resolve_tags(self, name: str) -> list:
        """Tag name/alias/synonym/typo -> VNDB tags (for the always-exclude list)."""
        t = self.index.by_name(name) or self.index.lookup(name)
        if t:
            return [t]
        m = self.parser.matcher.match(name, embeddings=False)
        ids = []
        for c in m.criteria if m else []:
            ids += [c.value] if c.kind == "tag" else c.value if c.kind == "tag_any" else []
        return [self.index.tags[i] for i in ids]
