"""Optional local-LLM rewriter (Ollama).

The LLM only turns a conversational request into the comma-separated keyword
line the rule parser already understands. It never builds filters or picks
tag IDs; the parser stays the sole authority. Any failure -> caller falls back
to parsing the original text.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import requests
from rapidfuzz import fuzz, process

SYSTEM = """You convert a visual-novel search request into short search keywords for a rule-based parser.

Output JSON: {"keywords": ["...", "..."]}. One requirement per keyword, 1-4 words each.

Rules:
- Only include requirements the user actually stated. Never add, guess or embellish.
- Prefer VNDB tag wording: "Female Protagonist", "Male Protagonist", "Multiple Endings", "Fantasy",
  "Vampire", "Maid Heroine", "Time Loop", "Strong Female Protagonist", "Kinetic Novel", "Otome Game".
- Exclusions start with "no": "no horror", "no sexual content", "no romance plot".
- Languages as a single word: "english", "japanese".
- Engines by name: "RPG Maker", "Ren'Py", "Wolf RPG Editor", "Unity", "KiriKiri", "TyranoScript".
- Platforms: "windows", "android", "linux", "mac", "switch".
- Length: "very short", "short", "medium", "long", "very long", "not too long".
- Dates: "after 2015", "before 2010", "2018-2022", "90s". Quality: "highly rated", "popular".
- Content level: "suggestive", "explicit", "all ages".
- Drop filler such as "I want", "please", "ideally", "something like".
- Use singular nouns ("vampire", not "vampires").
Known extra phrases the parser understands: {synonyms}
"""

FEW_SHOT = [
    ("I want a game involvings multiple endings, with a strong heroine, some maids",
     ["multiple endings", "strong heroine", "maid"]),
    ("I would love a dark story about vampires that was made in RPG Maker but has no horror "
     "elements, ideally released after 2015",
     ["dark", "vampire", "RPG Maker", "no horror", "after 2015"]),
    ("looking for something where you play as a girl, in english, not too long please",
     ["female protagonist", "english", "not too long"]),
]

KEYWORDS_SCHEMA = {"type": "object", "properties": {"keywords": {"type": "array", "items": {"type": "string"}}},
                   "required": ["keywords"]}
REPAIR_SCHEMA = {"type": "object", "properties": {"choices": {"type": "array", "items": {
    "type": "object", "properties": {"phrase": {"type": "string"}, "tag": {"type": "string"}},
    "required": ["phrase", "tag"]}}}, "required": ["choices"]}

REPAIR_PROMPT = """For each phrase below, pick the ONE tag from its candidate list that means the same thing,
or "none" if no candidate fits closely. Do not pick a tag that is merely related.
Output JSON: {"choices": [{"phrase": "...", "tag": "..."}]}

"""


@dataclass
class Rewrite:
    text: str | None     # None -> caller should parse the original input
    note: str = ""


class LLMRewriter:
    def __init__(self, cfg: dict, parser, session=None, log=print):
        self.cfg = cfg
        self.parser = parser
        self.log = log
        self.http = session or requests.Session()
        self.url = cfg.get("llm_url", "http://127.0.0.1:11434").rstrip("/") + "/api/chat"
        self.model = cfg.get("llm_model", "qwen2.5:7b-instruct")
        self.timeout = float(cfg.get("llm_timeout", 20))
        keys = sorted(parser.synonyms.entries)
        self.system = SYSTEM.replace("{synonyms}", ", ".join(keys))
        self.tag_names = [t.name for t in parser.index.tags.values()]

    def _chat(self, messages: list[dict], schema: dict) -> dict:
        r = self.http.post(self.url, timeout=self.timeout, json={
            "model": self.model, "messages": messages, "stream": False,
            "format": schema, "options": {"temperature": 0}, "keep_alive": "10m"})
        r.raise_for_status()
        return json.loads(r.json()["message"]["content"])

    def rewrite(self, text: str) -> Rewrite:
        msgs = [{"role": "system", "content": self.system}]
        for q, kw in FEW_SHOT:
            msgs += [{"role": "user", "content": q},
                     {"role": "assistant", "content": json.dumps({"keywords": kw})}]
        msgs.append({"role": "user", "content": text})
        try:
            kws = [str(k).strip() for k in self._chat(msgs, KEYWORDS_SCHEMA)["keywords"] if str(k).strip()]
        except requests.RequestException as e:
            return self._fail(f"Ollama not reachable at {self.url} ({type(e).__name__})")
        except (ValueError, KeyError, TypeError) as e:
            return self._fail(f"bad LLM output ({e})")
        if not kws:
            return self._fail("LLM returned no keywords")
        # the parser splits on commas, so keep them out of single keywords
        kws = [k.replace(",", " ") for k in kws]
        if self.cfg.get("llm_repair", True):
            kws = self._repair(kws)
        return Rewrite(", ".join(kws), f"rewritten by {self.model}")

    def _repair(self, kws: list[str]) -> list[str]:
        """One round: phrases the parser can't place get real tag names to choose from."""
        unmatched = [k for k in kws if self.parser.parse(k).unmatched]
        if not unmatched:
            return kws
        cands = {}
        for k in unmatched:
            core = k[3:] if k.lower().startswith("no ") else k
            names = [n for n, _, _ in process.extract(core, self.tag_names, scorer=fuzz.WRatio, limit=10)]
            emb = self.parser.matcher.embedder
            if emb is not None:   # semantic neighbours first ("bloodsucker" -> Vampire)
                sem = [self.parser.index.tags[i].name for i, _ in emb.match(core, top_k=6)]
                names = list(dict.fromkeys(sem + names))[:12]
            cands[k] = names
        prompt = REPAIR_PROMPT + "\n".join(f"- {k!r}: {cands[k]}" for k in unmatched)
        try:
            choices = self._chat([{"role": "user", "content": prompt}], REPAIR_SCHEMA)["choices"]
        except (requests.RequestException, ValueError, KeyError, TypeError) as e:
            self.log(f"LLM repair skipped ({e})")
            return kws
        pick = {c.get("phrase"): c.get("tag") for c in choices if isinstance(c, dict)}
        out = []
        for k in kws:
            tag = pick.get(k)
            if k in cands and tag in cands[k]:        # only accept a real offered candidate
                tag = f"no {tag}" if k.lower().startswith("no ") else tag
                out.append(tag)
            else:
                out.append(k)
        return out

    def _fail(self, why: str) -> Rewrite:
        self.log(f"LLM rewriter unavailable: {why}; using the rule parser on the original text")
        return Rewrite(None, why + " - used rule parser")
