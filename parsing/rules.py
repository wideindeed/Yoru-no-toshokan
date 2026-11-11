"""Rule-based extraction of structured fields from phrases.

Each rule finds its pattern anywhere in a phrase, emits Criterion objects and
removes the matched text. Whatever is left over goes to the tag matcher.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from parsing.model import Criterion

# ---------------------------------------------------------------- splitting
# Separators and clause words. Each piece is parsed on its own, and a
# negation only reaches to the end of its own piece.
_SPLIT_RE = re.compile(
    r"[,;\n:+&|!?]|\.\s|\.$"
    r"|\s+(?:and|but|plus|also|that|which|where|while|though|although|ideally|preferably|whereas)\s+"
    r"|(?<!\bnothing)(?<!\bno)(?<!\bany)(?<!\banything)\s+with\s+|^with\s+",
    re.I,
)
_NEG_RE = re.compile(
    r"^(?:no|not|without|exclude|excluding|except|minus|avoid|non)\b[\s-]*", re.I
)
# A negation trigger anywhere in a clause; everything after it is excluded.
# "not too/very/that ..." is a degree, not a negation (handled by rules).
_NEG_ANY_RE = re.compile(
    r"(?<![\w'])(?:"
    r"no|not|without|never|nothing|non"
    r"|don'?t\s+(?:want|like|need|include)|do\s+not\s+(?:want|like|need|include)"
    r"|doesn'?t\s+(?:have|include|contain)|does\s+not\s+(?:have|include|contain)"
    r"|isn'?t|aren'?t|hate|dislike|avoid(?:ing)?|exclude|excluding|except|minus"
    r"|free\s+of|lacking|skip|tired\s+of|sick\s+of|fed\s+up\s+with|don'?t\s+have"
    r")(?![\w'])(?!\s+(?:too|very|that|overly|so|super)\b)[\s-]*",
    re.I,
)

# Words that never carry search meaning on their own. They are skipped by
# the tag scanner and never reported as "not understood". Multi-word tag
# names containing them ("Protagonist with a Face") still match, because
# the scanner tries whole word windows before dropping stopwords.
STOPWORDS = set("""
a an the some any this these those such
i me my mine he him his she her hers i'd i'm i've id im ive we us our you your it its it's they them their there here
is are was were be been being am do does did done have has had having get got
want wants wanted wanting would could should can will must might may shall
like likes liked love loved prefer need needs needed wish hope hoping
looking look searching search find finding show give recommend recommendation suggest
something anything stuff thing things one ones kind sort type types lot lots plenty bunch
of in on at for to from with about into by as over under within onto
involving involve involves involved featuring feature features including include includes
containing contain contains centered centred focused focus focusing based
and or but so also plus then than where which that who whom whose while when
ideally preferably please maybe perhaps really just mostly mainly quite pretty very
somewhat especially definitely probably hopefully actually basically fairly kinda sorta
game games vn vns visual novel novels title titles story stories plot read reads
setting set themes theme elements element vibe vibes feel feeling atmosphere
made using built engine version
oh ah uh um hmm well yeah yes ok okay too much many more bit little
few see world main character characters protagonist
good great fine whats what's someone anyone once deal lol lmao pls plz tho
""".split())

# Kept for edge-stripping whole phrases (older, more conservative list).
FILLER = {
    "a", "an", "the", "some", "any", "game", "games", "vn", "vns",
    "visual", "novel", "novels", "visual novel", "visual novels",
    "with", "has", "having", "featuring", "about", "that", "which", "where",
    "made", "in", "on", "using", "built", "engine", "for", "of", "is",
    "i", "want", "looking", "something", "please", "like", "ones", "one",
    "set", "setting", "themes", "theme", "type", "kind", "elements",
}

# Words that carry no meaning on their own when left at the edge of a phrase.
FILLER = {
    "a", "an", "the", "some", "any", "game", "games", "vn", "vns",
    "visual", "novel", "novels", "visual novel", "visual novels",
    "with", "has", "having", "featuring", "about", "that", "which", "where",
    "made", "in", "on", "using", "built", "engine", "for", "of", "is",
    "i", "want", "looking", "something", "please", "like", "ones", "one",
    "set", "setting", "themes", "theme", "type", "kind", "elements",
}
_FILLER_ALT = "|".join(map(re.escape, sorted(FILLER, key=len, reverse=True)))
_FILLER_EDGE_RE = re.compile(
    rf"^(?:(?:{_FILLER_ALT})\b\W*)+|(?:\W*\b(?:{_FILLER_ALT}))+$", re.I
)
_BETWEEN_RE = re.compile(r"\bbetween\s+((?:19|20)\d{2})\s+and\s+((?:19|20)\d{2})\b", re.I)


def split_phrases(text: str) -> list[str]:
    text = _BETWEEN_RE.sub(r"\1-\2", text)  # keep year ranges intact through the " and " split
    parts = _SPLIT_RE.split(text)
    return [p.strip(" \t-'\"!?()[]{}").strip() for p in parts if p and p.strip(" \t-.'\"")]


def split_negation(phrase: str) -> tuple[bool, str]:
    m = _NEG_RE.match(phrase)
    if m and phrase[m.end():].strip():
        return True, phrase[m.end():].strip()
    return False, phrase


def strip_filler(text: str) -> str:
    prev = None
    text = text.strip()
    while prev != text:
        prev = text
        text = _FILLER_EDGE_RE.sub("", text).strip(" \t-/.,'\"")
    return text


def singular(text: str) -> str:
    """Naive singular of the last word ("time loops" -> "time loop")."""
    words = text.split()
    if not words:
        return text
    w = words[-1]
    if len(w) > 4 and w.endswith("ies"):
        w = w[:-3] + "y"
    elif len(w) > 4 and re.search(r"(sses|xes|ches|shes)$", w):
        w = w[:-2]
    elif len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    return " ".join(words[:-1] + [w])


_TOKEN_RE = re.compile(r"[\w][\w'’\-+]*", re.U)


def tokenize(text: str) -> list[str]:
    return [t.lower().replace("’", "'").rstrip("'-") for t in _TOKEN_RE.findall(text)]


def is_stop(token: str) -> bool:
    return token in STOPWORDS or singular(token) in STOPWORDS


#  "not just a power fantasy", "isn't only h scenes": a hedge, neither wanted nor excluded
_NOT_JUST_RE = re.compile(r"(?<![\w'])(?:not|isn'?t|aren'?t|wasn'?t)\s+(?:just|only|merely|simply|purely)\b.*$", re.I)


def split_on_negation(clause: str) -> tuple[str, str | None]:
    """Split at the first negation trigger: (positive part, negated part or None)."""
    clause = _NOT_JUST_RE.sub("", clause)
    m = _NEG_ANY_RE.search(clause)
    if not m or not clause[m.end():].strip():
        return clause, None
    return clause[: m.start()], clause[m.end():]


def has_negation(text: str) -> bool:
    return bool(_NEG_ANY_RE.search(text))


def is_empty_leftover(text: str) -> bool:
    return all(is_stop(t) for t in tokenize(text))


# ---------------------------------------------------------------- languages
# Codes from the VNDB /schema "language" enum.
LANGUAGES = {
    "arabic": "ar", "basque": "eu", "belarusian": "be", "bulgarian": "bg",
    "bosnian": "bs", "catalan": "ca", "chinese": "zh",
    "simplified chinese": "zh-Hans", "traditional chinese": "zh-Hant",
    "croatian": "hr", "czech": "cs", "danish": "da", "dutch": "nl",
    "english": "en", "esperanto": "eo", "estonian": "et", "finnish": "fi",
    "french": "fr", "galician": "gl", "german": "de", "greek": "el",
    "hebrew": "he", "hindi": "hi", "hungarian": "hu", "irish": "ga",
    "indonesian": "id", "italian": "it", "japanese": "ja", "kazakh": "kk",
    "korean": "ko", "latin": "la", "latvian": "lv", "lithuanian": "lt",
    "macedonian": "mk", "malay": "ms", "nepali": "ne", "norwegian": "no",
    "persian": "fa", "polish": "pl", "brazilian portuguese": "pt-br",
    "portuguese": "pt-br", "european portuguese": "pt-pt", "romanian": "ro",
    "russian": "ru", "serbian": "sr", "slovak": "sk", "slovene": "sl",
    "slovenian": "sl", "spanish": "es", "swedish": "sv", "tagalog": "ta",
    "thai": "th", "turkish": "tr", "ukrainian": "uk", "urdu": "ur",
    "vietnamese": "vi",
    # short forms (deliberately not "no"/"it"/"id": they collide with English words)
    "eng": "en", "en": "en", "jp": "ja", "jpn": "ja", "cn": "zh", "kr": "ko",
}
LANG_LABELS = {
    "en": "English", "ja": "Japanese", "zh": "Chinese", "zh-Hans": "Chinese (simplified)",
    "zh-Hant": "Chinese (traditional)", "ko": "Korean", "pt-br": "Portuguese (Brazil)",
    "pt-pt": "Portuguese (Portugal)",
}

# ---------------------------------------------------------------- platforms
# (pattern, [codes], label)
PLATFORMS = [
    (r"windows|win|pc|win32|win64", ["win"], "Windows"),
    (r"linux", ["lin"], "Linux"),
    (r"mac\s?os|macos|osx|mac", ["mac"], "Mac"),
    (r"android", ["and"], "Android"),
    (r"ios|iphone|ipad", ["ios"], "iOS"),
    (r"mobile|phone", ["and", "ios", "mob"], "Mobile"),
    (r"(?:nintendo\s)?switch\s?2", ["sw2"], "Switch 2"),
    (r"(?:nintendo\s)?switch", ["swi"], "Switch"),
    (r"(?:nintendo\s)?3ds", ["n3d"], "3DS"),
    (r"nintendo\sds|nds", ["nds"], "Nintendo DS"),
    (r"ps\s?vita|playstation\svita|vita", ["psv"], "PS Vita"),
    (r"psp", ["psp"], "PSP"),
    (r"ps\s?5|playstation\s?5", ["ps5"], "PS5"),
    (r"ps\s?4|playstation\s?4", ["ps4"], "PS4"),
    (r"ps\s?3|playstation\s?3", ["ps3"], "PS3"),
    (r"ps\s?2|playstation\s?2", ["ps2"], "PS2"),
    (r"xbox\s?one", ["xbo"], "Xbox One"),
    (r"xbox\s?series(?:\s?[xs/]+)?", ["xxs"], "Xbox Series"),
    (r"web\s?browser|browser|web", ["web"], "Web"),
    (r"dreamcast", ["drc"], "Dreamcast"),
    (r"pc-?98", ["p98"], "PC-98"),
]

# ---------------------------------------------------------------- engines
# Verified against live data: VNDB stores every RPG Maker version as plain
# "RPG Maker", so version words are swallowed and ignored.
_RPGM_VER = r"(?:\s?(?:xp|vx\s?ace|vx|mv|mz|2000|2003|2k3|2k|95))?"
ENGINES = [
    (r"rpg\s?maker" + _RPGM_VER + r"|rpgm" + _RPGM_VER, "RPG Maker"),
    (r"wolf\s?rpg(?:\s?editor)?|wolf\s?editor", "Wolf RPG Editor"),
    (r"ren'?\s?py", "Ren'Py"),
    (r"kiri\s?kiri(?:\s?z)?|krkrz?", "KiriKiri"),
    (r"tyrano\s?(?:builder|script)?", "TyranoScript"),
    (r"visual\s?novel\s?maker", "Visual Novel Maker"),
    (r"unity(?:\s?engine)?", "Unity"),
    (r"o?nscripter", "NScripter"),
    (r"godot(?:\s?engine)?", "Godot"),
    (r"game\s?maker(?:\s?studio(?:\s?2)?)?", "GameMaker"),
    (r"unreal(?:\s?engine)?", "Unreal Engine"),
    (r"reallive", "RealLive"),
]

LENGTHS = {"very short": 1, "short": 2, "medium": 3, "average length": 3,
           "long": 4, "very long": 5}
LENGTH_LABELS = {1: "Very short", 2: "Short", 3: "Medium", 4: "Long", 5: "Very long"}
_LENGTH_RE = re.compile(
    r"^(?:length\s*[:=]?\s*)?(very short|very long|average length|short|medium|long)"
    r"(?:\s+(?:games?|vns?|visual novels?|ones?|story|stories|length|reads?|playtime))?$",
    re.I,
)


def _wb(p: str) -> re.Pattern:
    return re.compile(r"(?<![\w'])(?:" + p + r")(?![\w'])", re.I)


_HOURS_RE = _wb(r"(?:(under|less\s+than|below|at\s+most|max(?:imum)?|up\s+to|within|over|more\s+than|at\s+least|about|around)\s+)?"
               r"(\d+)\s*\+?\s*(?:h|hrs?|hours?)(?:\s+(?:long|max|or\s+(?:less|so)))?")
_NOISE_RE = _wb(r"on\s+(?:my\s+|a\s+)?(?:lunch|coffee)\s+break|for\s+once|type\s+deal")


def _hours_bucket(h: int) -> int:
    return 1 if h < 2 else 2 if h <= 10 else 3 if h <= 30 else 4 if h <= 50 else 5


_LENGTH_NOUN_RE = _wb(r"(very short|very long|short|long)\s+(?:games?|vns?|visual novels?|reads?)")


_LANG_RE = _wb(
    r"(?:in\s+|translated\s+(?:to|into)\s+)?("
    + "|".join(re.escape(k) for k in sorted(LANGUAGES, key=len, reverse=True))
    + r")(?:\s+(?:translation|translated|tl|language|version|patch|release|text))?"
)
_LANG_ALT = "|".join(re.escape(k) for k in sorted(LANGUAGES, key=len, reverse=True))
_TL_WHO = r"(official(?:ly)?|licen[cs]ed|fan[\s-]?made|fan|unofficial)"
_TL_NOUN = r"(?:translations?|translated|tls?|locali[sz]ations?|locali[sz]ed|patch(?:es|ed)?)"
_TL_RE = _wb(_TL_WHO + r"\s+(?:(" + _LANG_ALT + r")\s+)?" + _TL_NOUN
             + r"(?:\s+(?:in|to|into)\s+(" + _LANG_ALT + r"))?"
             r"|" + _TL_WHO + r"\s+(" + _LANG_ALT + r")(?:\s+(?:releases?|versions?))?")
_PLATFORM_RES = [(_wb(r"(?:on\s+|for\s+)?(?:" + p + r")(?:\s+(?:version|port|release))?"), codes, label)
                 for p, codes, label in PLATFORMS]
_ENGINE_RES = [(_wb(r"(?:made\s+(?:in|with|using)\s+|built\s+(?:in|with)\s+)?(?:"
                    + p + r")(?:\s+(?:engine|games?))?"), name) for p, name in ENGINES]

_YEAR = r"((?:19|20)\d{2})"
_RANGE_RE = _wb(r"(?:from\s+|between\s+)?" + _YEAR + r"\s*(?:-|–|to|until|and|through)\s*" + _YEAR)
_AFTER_RE = _wb(r"(?:released\s+)?(after|since|from|newer\s+than|post|later\s+than)\s+" + _YEAR)
_BEFORE_RE = _wb(r"(?:released\s+)?(before|until|till|older\s+than|pre|earlier\s+than|up\s+to)\s+" + _YEAR)
_INYEAR_RE = _wb(r"(?:released\s+)?in\s+" + _YEAR + r"|" + _YEAR)
_DECADE_RE = _wb(r"(?:the\s+)?(?:(19|20)?(\d)0)'?s")

_HIGH_RATED_RE = _wb(
    r"(?:highly|high|top|well|best|good|great)[\s-]?(?:rated|rating|ratings|reviewed|scored)"
    r"|highly\s+regarded|acclaimed|masterpieces?"
)
_NOT_TOO_RE = _wb(r"(?:not|isn'?t|nothing)\s+(?:too|very|that|overly|so|super)\s+(long|short)")
_POPULAR_RE = _wb(r"popular|well[\s-]known|famous|mainstream")


@dataclass
class RuleOutput:
    criteria: list[Criterion]
    leftover: str


def _year_range(lo: int | None, hi: int | None) -> list[list[str]]:
    """Inclusive year bounds -> list of [op, date] that are safe with VNDB's
    partial-date ordering ("2022" sorts after "2022-12-31")."""
    out = []
    if lo is not None:
        out.append([">=", f"{lo}-01-01"])
    if hi is not None:
        out.append(["<", f"{hi + 1}-01-01"])
    return out


def _date_label(lo, hi) -> str:
    if lo and hi:
        return f"Released {lo}" if lo == hi else f"Released {lo}–{hi}"
    if lo:
        return f"Released {lo} or later"
    return f"Released {hi} or earlier"


def extract(phrase: str, cfg: dict, exclude: bool = False, person: bool = False) -> RuleOutput:
    """person: the clause describes someone, so a bare "short" is their height, not the length."""
    out: list[Criterion] = []
    text = phrase

    def add(kind, value, label, op="="):
        out.append(Criterion(kind=kind, value=value, label=label, op=op,
                             exclude=exclude, phrase=phrase, method="rule"))

    def cut(m: re.Match) -> str:
        return text[: m.start()] + " " + text[m.end():]

    # engines first ("visual novel maker" must beat the "visual novel" filler)
    for rx, name in _ENGINE_RES:
        m = rx.search(text)
        if m:
            add("engine", name, f"Engine: {name}")
            text = cut(m)

    # dates
    for rx, kind in ((_RANGE_RE, "range"), (_AFTER_RE, "after"), (_BEFORE_RE, "before"),
                     (_DECADE_RE, "decade"), (_INYEAR_RE, "year")):
        m = rx.search(text)
        if not m:
            continue
        if kind == "range":
            lo, hi = sorted((int(m.group(1)), int(m.group(2))))
        elif kind == "after":
            y = int(m.group(2))
            lo, hi = (y + 1 if m.group(1).lower() in ("after", "post", "newer than", "later than") else y), None
        elif kind == "before":
            y = int(m.group(2))
            lo, hi = None, (y - 1 if m.group(1).lower() in ("before", "pre", "older than", "earlier than") else y)
        elif kind == "decade":
            century = m.group(1) or ("19" if int(m.group(2)) >= 7 else "20")
            lo = int(f"{century}{m.group(2)}0")
            hi = lo + 9
        else:
            y = int(m.group(1) or m.group(2))
            lo = hi = y
        add("released", _year_range(lo, hi), _date_label(lo, hi))
        text = cut(m)
        break

    # quality
    m = _HIGH_RATED_RE.search(text)
    if m:
        add("rating", int(cfg["high_rating_min"]), f"Rating ≥ {cfg['high_rating_min']}", op=">=")
        text = cut(m)
    m = _POPULAR_RE.search(text)
    if m:
        add("votecount", int(cfg["popular_min_votes"]), f"Votes ≥ {cfg['popular_min_votes']}", op=">=")
        text = cut(m)

    # translations: "official english translation", "fan tl", "officially translated into french"
    m = _TL_RE.search(text)
    if m:
        who = (m.group(1) or m.group(4)).lower()
        lang = m.group(2) or m.group(3) or m.group(5)
        code = LANGUAGES[lang.lower()] if lang else "en"
        name = LANG_LABELS.get(code, lang.title() if lang else "English")
        official = not who.startswith(("fan", "unofficial"))
        add("tl", [code, official], f"Official {name} translation" if official else f"Fan translation ({name})")
        text = cut(m)

    # languages (may appear several times: "english or japanese")
    while True:
        m = _LANG_RE.search(text)
        if not m:
            break
        code = LANGUAGES[m.group(1).lower()]
        add("lang", [code], LANG_LABELS.get(code, m.group(1).title()))
        text = cut(m)

    # platforms ("windows/pc" hits the same rule twice; the parser dedupes)
    for rx, codes, label in _PLATFORM_RES:
        while m := rx.search(text):
            add("platform", list(codes), label)
            text = cut(m)

    # degree phrases: "not too long" -> at most Medium, "not too short" -> at least Medium
    m = _NOT_TOO_RE.search(text)
    if m:
        if m.group(1).lower() == "long":
            add("length", 3, "Length: Medium or shorter", op="<=")
        else:
            add("length", 3, "Length: Medium or longer", op=">=")
        text = cut(m)

    text = _NOISE_RE.sub(" ", text)
    # "under 5 hours", "100 hours", "at least 30h"
    if m := _HOURS_RE.search(text):
        word, h = (m.group(1) or "").lower(), int(m.group(2))
        if word in ("under", "less than", "below", "at most", "max", "maximum", "up to", "within"):
            n = _hours_bucket(h - 1) if h > 1 else 1
            add("length", n, f"Length: {LENGTH_LABELS[n]}" + (" or shorter" if n > 1 else ""), op="<=")
        elif word in ("over", "more than", "at least") or "+" in m.group(0):
            n = _hours_bucket(h)
            add("length", n, f"Length: {LENGTH_LABELS[n]}" + (" or longer" if n < 5 else ""), op=">=")
        else:
            n = _hours_bucket(h)
            add("length", n, f"Length: {LENGTH_LABELS[n]}")
        text = cut(m)

    # length: only when (nearly) the whole remaining phrase is a length word,
    # so "long hair" or "short story collection" are left for the tag matcher.
    m = _LENGTH_RE.match(strip_filler(text))
    hours = any(c.kind == "length" for c in out)    # "short vn under 5 hours": the hours say it already
    if m and person and m.group(0).lower() == m.group(1).lower():
        m = None
    if m:
        n = LENGTHS[m.group(1).lower()]
        if not hours:
            add("length", n, f"Length: {LENGTH_LABELS[n]}")
        text = ""
    elif hours:
        text = _LENGTH_NOUN_RE.sub(" ", text)
    # ...or a length word naming the game itself inside a longer phrase
    # ("a short visual novel I can finish fast"); "short hair" still isn't one.
    elif m := _LENGTH_NOUN_RE.search(text):
        n = LENGTHS[m.group(1).lower()]
        add("length", n, f"Length: {LENGTH_LABELS[n]}")
        text = cut(m)

    return RuleOutput(out, re.sub(r"\s+", " ", text).strip())
