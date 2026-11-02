"""Command-line search.

  python cli.py "fantasy, english, rpg maker, female lead" [--explain] [--sort votecount]
  python cli.py --refresh-tags
"""
from __future__ import annotations

import argparse
import json
import sys

from finder import Finder
from settings import load_config


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows consoles
    ap = argparse.ArgumentParser(description="Natural-language VNDB search")
    ap.add_argument("query", nargs="?", help="what you are looking for")
    ap.add_argument("--explain", action="store_true", help="show how every phrase was matched")
    ap.add_argument("--refresh-tags", action="store_true", help="re-download the VNDB tag list")
    ap.add_argument("--sort", choices=["rating", "votecount", "released", "title"])
    ap.add_argument("--any", action="store_true", help="match ANY tag (re-ranked by tag hits)")
    ap.add_argument("--no-prefs", action="store_true", help="ignore the always-exclude list and hidden VNs")
    ap.add_argument("--mature", action="store_true", help="only sexual-content VNs (default: none of them)")
    ap.add_argument("-n", "--results", type=int, default=10)
    ap.add_argument("--page", type=int, default=1)
    llm = ap.add_mutually_exclusive_group()
    llm.add_argument("--llm", dest="llm", action="store_true", default=None, help="force the LLM rewriter on")
    llm.add_argument("--no-llm", dest="llm", action="store_false", help="force the LLM rewriter off")
    args = ap.parse_args(argv)

    if not args.query and not args.refresh_tags:
        ap.error("give a query or --refresh-tags")
    finder = Finder(load_config(), refresh_tags=args.refresh_tags)
    if not args.query:
        print(f"{len(finder.index.tags)} tags cached.")
        return 0

    res, rewritten, note = finder.interpret(args.query, use_llm=args.llm)
    if rewritten is not None:
        print(f"Rewritten as: {rewritten}")
    if note:
        print(f"(LLM: {note})")
    print("Understood as: " + "  ".join(f"[{c.display}]" for c in res.criteria))
    if res.unmatched:
        print("Not understood: " + "  ".join(f"[{u}]" for u in res.unmatched))
    if args.explain:
        print("\nPhrases:")
        for r in res.report:
            got = ", ".join(c.display for c in r.criteria) or "-"
            print(f"  {r.phrase!r:55} {r.method:22} {r.score:5.1f}  -> {got}")

    out = finder.search(res.criteria, sort=args.sort, mode="any" if args.any else "all",
                        page=args.page, mature=args.mature, use_prefs=not args.no_prefs, results=args.results)
    if args.explain:
        print("\nFilters: " + json.dumps(out.filters, ensure_ascii=False))
    for n in out.notes:
        print(n)
    print(f"\nResults (sort: {out.sort}, page {out.page}{', more available' if out.more else ''}):")
    if not out.cards:
        print("  nothing found - try removing a criterion")
    for c in out.cards:
        rating = f"{c['rating']:.2f}" if c["rating"] else "  -  "
        hits = f" [{c['hits']}/{c['wanted']} tags]" if args.any and c["wanted"] else ""
        print(f"  {rating}  {c['title']} ({c['year'] or '?'}){hits}  {c['url']}")
        if c["tags"]:
            print(f"         {', '.join(c['tags'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
