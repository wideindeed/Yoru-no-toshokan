"""Personal preferences kept in data/prefs.json:
- exclude: tags always excluded, one list per layer ("normal" = Mature off, "mature" = Mature on;
           "ln_normal" / "ln_mature" for light novels, whose tags are AniList's)
- hidden:  VNs and light novels ("l..." ids) marked "not interested", never shown again
- vndb_list: an imported VNDB list {user, items: {vid: vote}, taste: [criteria]} (see like.read_list)
"""
from __future__ import annotations

import json
from pathlib import Path

PREFS_PATH = Path(__file__).resolve().parent / "data" / "prefs.json"
LAYERS = ("normal", "mature", "ln_normal", "ln_mature")


class Prefs:
    def __init__(self, path: Path = PREFS_PATH):
        self.path = Path(path)
        data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        ex = data.get("exclude") or {}
        self.exclude: dict[str, list[dict]] = {l: list(ex.get(l) or []) for l in LAYERS}   # [{id, name}]
        self.hidden: dict[str, str] = dict(data.get("hidden") or {})                       # vid -> title
        self.vndb_list: dict | None = data.get("vndb_list")

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"exclude": self.exclude, "hidden": self.hidden,
                                                    "vndb_list": self.vndb_list},
                                        indent=2, ensure_ascii=False), encoding="utf-8")

    def layer(self, mature: bool, source: str = "vn") -> str:
        return ("ln_" if source == "ln" else "") + ("mature" if mature else "normal")

    def add_exclude(self, layer: str, tag_id: str, name: str):
        if layer in LAYERS and all(t["id"] != tag_id for t in self.exclude[layer]):
            self.exclude[layer].append({"id": tag_id, "name": name})
            self.save()

    def remove_exclude(self, layer: str, tag_id: str):
        if layer in LAYERS:
            self.exclude[layer] = [t for t in self.exclude[layer] if t["id"] != tag_id]
            self.save()

    def hide(self, vid: str, title: str):
        self.hidden[vid] = title or vid
        self.save()

    def unhide(self, vid: str):
        if self.hidden.pop(vid, None) is not None:
            self.save()

    def set_list(self, data: dict | None):
        self.vndb_list = data
        self.save()

    def to_dict(self) -> dict:
        return {"exclude": self.exclude,
                "hidden": [{"id": k, "title": v} for k, v in self.hidden.items()],
                "vndb_list": self.vndb_list}
