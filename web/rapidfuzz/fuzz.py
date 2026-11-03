from difflib import SequenceMatcher


def ratio(a, b, **_):
    if not a and not b:
        return 100.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio() * 100


def token_sort_ratio(a, b, **_):
    return ratio(" ".join(sorted(a.split())), " ".join(sorted(b.split())))


def token_set_ratio(a, b, **_):
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    inter, da, db = ta & tb, ta - tb, tb - ta
    if inter and (not da or not db):
        return 100.0
    s = " ".join(sorted(inter))
    sa = (s + " " + " ".join(sorted(da))).strip()
    sb = (s + " " + " ".join(sorted(db))).strip()
    return max(ratio(s, sa) if s else 0, ratio(s, sb) if s else 0, ratio(sa, sb))
