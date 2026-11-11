"""Glue shared by cli.py and app.py: text -> (rewrite) -> parse -> query -> cards.

Two sources: "vn" (VNDB) and "ln" (light novels from AniList, set up on first use)."""
from __future__ import annotations

from dataclasses import dataclass, field

import details
import like
from prefs import Prefs
import query_builder as qb
from parsing.model import Criterion, ParseResult
from parsing.parser import QueryParser
from settings import load_config
from vndb.client import VNDBClient, VNDBError
from vndb.tags import load_tag_index

SOURCES = ("vn", "ln")


@dataclass
class SearchResult:
    cards: list[dict]
    more: bool
    filters: object
    page: int
    sort: str
    mode: str
    notes: list[str] = field(default_factory=list)


class LightNovels:
    """AniList side: its own client, tag index, parser and tag browser."""

    def __init__(self, cfg: dict, refresh_tags: bool = False, log=print):
        from anilist import tags as al_tags
        from anilist.client import AniListClient
        self.client = AniListClient(cfg)
        self.index = al_tags.load_tag_index(self.client, refresh=refresh_tags, config=cfg, log=log)
        self.parser = QueryParser(self.index, cfg, log=log, source="ln")
        self.browser = None
        self.rewriter = None


class Finder:
    def __init__(self, cfg: dict | None = None, refresh_tags: bool = False, log=print):
        self.cfg = cfg or load_config()
        self.log = log
        self.refresh_tags = refresh_tags
        self.client = VNDBClient(self.cfg)
        self.index = load_tag_index(self.client, refresh=refresh_tags, config=self.cfg, log=log)
        self.parser = QueryParser(self.index, self.cfg, log=log)
        self.browser = None            # TagBrowser, built on first use by app.py
        self.prefs = Prefs()
        self.rewriter = None
        self._ln: LightNovels | None = None
        if self.cfg.get("use_llm"):
            from parsing.llm_rewrite import LLMRewriter
            self.rewriter = LLMRewriter(self.cfg, self.parser, log=log)

    @property
    def ln(self) -> LightNovels:
        if self._ln is None:
            self._ln = LightNovels(self.cfg, self.refresh_tags, log=self.log)
        return self._ln

    def side(self, source: str):
        """Whatever holds index / parser / browser / rewriter for a source."""
        return self.ln if source == "ln" else self

    # ---------------------------------------------------------------- parse
    def interpret(self, text: str, use_llm: bool | None = None,
                  source: str = "vn") -> tuple[ParseResult, str | None, str]:
        """Returns (parse result, rewritten text or None, note about the LLM)."""
        side = self.side(source)
        use_llm = bool(self.cfg.get("use_llm")) if use_llm is None else use_llm
        if use_llm and side.rewriter is None:
            from parsing.llm_rewrite import LLMRewriter
            side.rewriter = LLMRewriter(self.cfg, side.parser, log=self.log)
        if use_llm:
            rw = side.rewriter.rewrite(text)
            if rw.text is not None:
                return side.parser.parse(rw.text), rw.text, rw.note
            return side.parser.parse(text), None, rw.note
        return side.parser.parse(text), None, ""

    # --------------------------------------------------------------- search
    def search(self, criteria: list[Criterion], sort: str | None = None, mode: str = "all",
               page: int = 1, mature: bool = False, results: int | None = None,
               skip_excludes=(), use_prefs: bool = True, source: str = "vn") -> SearchResult:
        """skip_excludes: always-excluded tag ids dropped for this search only."""
        from anilist import query as aq
        sort = sort if sort in (aq.SORTS if source == "ln" else qb.SORTS) else self.cfg["default_sort"]
        n = int(results or self.cfg["results_per_page"])
        crits = list(criteria)
        if use_prefs:
            crits += [Criterion("tag", t["id"], t["name"], exclude=True)
                      for t in self.prefs.exclude[self.prefs.layer(mature, source)] if t["id"] not in skip_excludes]
        if source == "ln":
            return self._search_ln(criteria, crits, sort, mode, page, mature, n, use_prefs)
        filters = qb.build_filters(crits, self.cfg, mode=mode, mature=mature)
        hidden = [v for v in self.prefs.hidden if v.startswith("v")] if use_prefs else []
        if hidden:   # "not interested" VNs never come back
            filters = qb._and([filters, *[["id", "!=", v] for v in hidden]])
        field, reverse = qb.api_sort(sort)
        data = self.client.query("vn", filters=filters, fields=qb.VN_FIELDS, sort=field,
                                 reverse=reverse, results=n, page=page)
        groups = qb.wanted_tag_groups(criteria)
        cards = [qb.to_card(v, self.cfg, groups, mature) for v in data.get("results", [])]
        if mode == "any" and groups:
            cards.sort(key=lambda c: -c["hits"])   # stable: keeps API order within a hit count
        notes = []
        if mode == "all" and page == 1 and len(cards) < n:
            # too few have every tag: add the closest matches (all tags but one, then two...)
            seen, pool = {c["id"] for c in cards}, []
            for level in qb.relaxed(crits):
                for cs in level:
                    f = qb.build_filters(cs, self.cfg, mode="all", mature=mature)
                    if hidden:
                        f = qb._and([f, *[["id", "!=", v] for v in hidden]])
                    for v in self.client.query("vn", filters=f, fields=qb.VN_FIELDS, sort=field,
                                               reverse=reverse, results=n, page=1).get("results", []):
                        if v["id"] not in seen:
                            seen.add(v["id"])
                            pool.append(v)
                if len(cards) + len(pool) >= n:
                    break
            close = qb.rank_close([qb.to_card(v, self.cfg, groups, mature) for v in pool], sort, n - len(cards))
            if close:
                notes.append(qb.close_note(len(cards)))
                cards += close
        if not criteria:
            notes.append("No criteria understood; showing top VNDB results.")
        if qb.content_in_query(criteria):
            notes.append("Your content words override the Mature toggle.")
        return SearchResult(cards, bool(data.get("more")), filters, page, sort, mode, notes)

    def _search_ln(self, criteria, crits, sort, mode, page, mature, n, use_prefs) -> SearchResult:
        from anilist import query as aq
        hidden = [h for h in self.prefs.hidden if h.startswith(aq.LN_PREFIX)] if use_prefs else []
        q, notes = aq.build(crits, self.ln.index, self.cfg, mode=mode, mature=mature, page=page,
                            sort=sort, hidden=hidden, per_page=n)
        media, more = aq.merge(self.ln.client.gql(q), sort)
        groups = qb.wanted_tag_groups(criteria)
        cards = [aq.to_card(m, self.cfg, groups, mature) for m in media]
        if mode == "any" and groups:
            cards.sort(key=lambda c: -c["hits"])
        if not criteria:
            notes.append("No criteria understood; showing top AniList light novels.")
        return SearchResult(cards, more, q, page, sort, mode, notes)

    # ------------------------------------------------------- like this one
    def _lookup(self, source: str, item_id: str | None = None, search: str | None = None):
        """(id, title, tags) of one title by id or best title match, or None."""
        if source == "ln":
            try:
                return like.from_ln(self.ln.client.gql(like.ln_request(item_id, search)).get("Media"))
            except VNDBError as e:
                if "404" in str(e):   # AniList's answer for "no such title"
                    return None
                raise
        body = like.vn_request(item_id, search)
        rows = self.client.query("vn", filters=body["filters"], fields=body["fields"],
                                 sort=body.get("sort"), results=body["results"]).get("results") or []
        return like.from_vn(like.best_vn(rows))

    def like(self, item_id: str, target: str = "vn") -> list[Criterion]:
        """Criteria for "more like this" (target = same library) or "same feel" in the other one."""
        source = "ln" if item_id.startswith("l") else "vn"
        found = self._lookup(source, item_id=item_id)
        t = self.side(target)
        return like.like_criteria(found, source, self.side(source).index, target, (t.index, t.parser.matcher))

    def expand_likes(self, crits: list[Criterion], source: str = "vn") -> tuple[list[Criterion], list[str]]:
        """Swap each "like <title>" for that title's tags (looked up in this library)."""
        out, notes = [], []
        for c in crits:
            if c.kind != "like":
                out.append(c)
                continue
            found = self._lookup(source, search=c.value)
            new = like.like_criteria(found, source, self.side(source).index, source)
            if new:
                notes.append(f"Like {found[1]}: searching for its main tags.")
                out += [x for x in new if all(x.key() != y.key() for y in out)]
            else:
                notes.append(f"No title found for \"{c.value}\".")
        return out, notes

    def import_list(self, username: str) -> dict:
        """Read a VNDB user's public list into prefs (titles seen + a taste profile)."""
        try:
            r = self.client.session.get(like.user_url(self.client.base, username), timeout=self.client.timeout)
            r.raise_for_status()
        except Exception as e:
            raise VNDBError(f"user lookup failed: {e}") from None
        who = like.user_id(r.json(), username)
        if who is None:
            raise ValueError(f"no VNDB user called {username!r}")
        rows = []
        for page in range(1, like.LIST_PAGES + 1):
            body = like.ulist_request(who[0], page)
            data = self.client.post("ulist", body, use_cache=False)
            rows += data.get("results") or []
            if not data.get("more"):
                break
        out = {"user": who[1], **like.read_list(rows, self.index)}
        self.prefs.set_list(out)
        return out

    # -------------------------------------------------------------- details
    def details(self, vid: str, mature: bool = False) -> dict | None:
        """One VN for the detail page (one cached API call)."""
        data = self.client.query("vn", filters=["id", "=", vid], fields=details.DETAIL_FIELDS, results=1)
        rows = data.get("results") or []
        return details.shape(rows[0], self.cfg, mature) if rows else None

    def ln_details(self, lid: str, mature: bool = False) -> dict | None:
        """One light novel for the detail page (one cached AniList call)."""
        from anilist import query as aq
        mid = aq.media_id(lid)
        if mid is None:
            return None
        m = self.ln.client.gql(aq.detail_query(mid)).get("Media")
        return aq.shape(m, self.cfg, mature) if m else None

    # ---------------------------------------------------------------- prefs
    def resolve_tags(self, name: str, source: str = "vn") -> list:
        """Tag name/alias/synonym/typo -> tags (for the always-exclude list)."""
        side = self.side(source)
        t = side.index.by_name(name) or side.index.lookup(name)
        if t:
            return [t]
        m = side.parser.matcher.match(name, embeddings=False)
        ids = []
        for c in m.criteria if m else []:
            ids += [c.value] if c.kind == "tag" else c.value if c.kind == "tag_any" else []
        return [side.index.tags[i] for i in ids]
