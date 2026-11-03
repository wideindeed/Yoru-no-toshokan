"""Pure-Python stand-in for rapidfuzz.process.extract."""

def extract(query, choices, scorer, score_cutoff=0, limit=5, **_):
    out = []
    for i, c in enumerate(choices):
        sc = scorer(query, c)
        if sc >= score_cutoff:
            out.append((c, sc, i))
    out.sort(key=lambda t: -t[1])
    return out[:limit]
