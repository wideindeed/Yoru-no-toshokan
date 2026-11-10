"""Build the browser-only version into site/ (static files for GitHub Pages).

    python build_web.py            # uses data/tags.json, downloading it if missing or stale
    python -m http.server -d site  # try it at http://localhost:8000

The page runs the parser in Pyodide; site/py.zip holds the Python it needs.
"""
from __future__ import annotations

import shutil
import zipfile

from settings import DATA_DIR, ROOT
from anilist import tags as al_tags
from vndb.tags import TAGS_PATH, load_tag_index

SITE = ROOT / "site"
PY_FILES = ["settings.py", "config.yaml", "query_builder.py", "details.py",
            "parsing/__init__.py", "parsing/model.py", "parsing/rules.py", "parsing/matcher.py",
            "parsing/parser.py", "parsing/tag_browser.py", "parsing/synonyms.yaml",
            "vndb/__init__.py", "vndb/tags.py", "vndb/labels.py",
            "anilist/__init__.py", "anilist/tags.py", "anilist/query.py"]
WEB_PY = ["web.py", "rapidfuzz/__init__.py", "rapidfuzz/fuzz.py", "rapidfuzz/process.py"]
STATIC = {"web/index.html": "index.html", "web/about.html": "about.html", "web/app.js": "app.js", "static/tagbrowser.js": "tagbrowser.js", "static/related.js": "related.js",
          "static/favicon.svg": "favicon.svg",
          "static/style.css": "style.css", "web/web.css": "web.css", "LICENSE": "LICENSE.txt"}


def _anilist():
    from anilist.client import AniListClient
    from settings import load_config
    return AniListClient(load_config())


def main():
    load_tag_index()   # refreshes data/tags.json if it's missing or older than tag_refresh_days
    al_tags.load_tag_index(_anilist())   # same for data/anilist_tags.json (light novels)
    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir()
    for src, dst in STATIC.items():
        shutil.copy(ROOT / src, SITE / dst)
    with zipfile.ZipFile(SITE / "py.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in PY_FILES:
            z.write(ROOT / f, f)
        for f in WEB_PY:
            z.write(ROOT / "web" / f, f)
        z.write(TAGS_PATH, "data/tags.json")
        z.write(al_tags.TAGS_PATH, "data/anilist_tags.json")
    shutil.copytree(ROOT / "static" / "vectors", SITE / "vectors")   # from `python -m parsing.embed`
    (SITE / ".nojekyll").touch()
    size = (SITE / "py.zip").stat().st_size // 1024
    print(f"Built {SITE} (py.zip {size} KB, tags from {DATA_DIR / 'tags.json'})")


if __name__ == "__main__":
    main()
