"""Compact, self-organising memory for the training area (ADR-0004).

Files in engine/knowledge (shipped with the app):
  <app>.learned.yaml  — demonstrated cards + extra phrasings for existing cards ("extends")
  <app>.pending.yaml  — cards whose demonstration failed, with the reason (for the developer to review)
  notes.yaml          — short knowledge notes (rephrased, with citations); merged when two say the same thing
  training_log.json   — one line per source: name, hash, date, counts. Never the source text.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import yaml
from rapidfuzz import fuzz

from ..intent.knowledge import KNOWLEDGE_DIR, fold
from .extract import signature

APPS = ("excel", "word", "powerpoint")
MAX_KEYWORDS = 14
MAX_NOTES_PER_APP = 400
_lock = threading.RLock()


def _load_yaml(p: Path, default: dict) -> dict:
    if not p.exists():
        return default
    return yaml.safe_load(p.read_text(encoding="utf-8")) or default


def _save_yaml(p: Path, data: dict, header: str):
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=140)
    p.write_text(header + text, encoding="utf-8")


HEADER = ("# Learned by the training area (ADR-0004) — generated, reviewed by demonstration. Edit or delete freely;\n"
          "# the base pack is <app>.cards.yaml.\n")


def _uniq_keywords(words: list[str]) -> list[str]:
    seen, out = set(), []
    for w in words:
        f = fold(w)
        if f and f not in seen:
            seen.add(f)
            out.append(w.strip())
    return out[:MAX_KEYWORDS]


class Memory:
    def __init__(self, root: Path = KNOWLEDGE_DIR):
        self.root = root

    def learned_path(self, app): return self.root / f"{app}.learned.yaml"
    def pending_path(self, app): return self.root / f"{app}.pending.yaml"
    @property
    def notes_path(self): return self.root / "notes.yaml"
    @property
    def log_path(self): return self.root / "training_log.json"

    # ---- cards ----------------------------------------------------------------------------
    def learned(self, app: str) -> dict:
        return _load_yaml(self.learned_path(app), {"version": 1, "app": app, "cards": [], "extends": {}})

    def find_same(self, card: dict, app: str) -> tuple[str, str] | None:
        """('base'|'learned', id) of a card with the same button sequence."""
        sig = signature(card)
        base = _load_yaml(self.root / f"{app}.cards.yaml", {"cards": []})
        for c in base.get("cards", []):
            if signature(c) == sig:
                return "base", c["id"]
        for c in self.learned(app).get("cards", []):
            if signature(c) == sig:
                return "learned", c["id"]
        return None

    def merge_keywords(self, app: str, where: str, card_id: str, keywords: list[str]) -> None:
        with _lock:
            data = self.learned(app)
            if where == "learned":
                for c in data["cards"]:
                    if c["id"] == card_id:
                        c["keywords"] = _uniq_keywords(c.get("keywords", []) + keywords)
            else:
                ext = data.setdefault("extends", {})
                ext[card_id] = _uniq_keywords(ext.get(card_id, []) + keywords)
            _save_yaml(self.learned_path(app), data, HEADER)

    def add_card(self, app: str, card: dict) -> None:
        with _lock:
            data = self.learned(app)
            data["cards"] = [c for c in data["cards"] if c["id"] != card["id"]] + [card]
            _save_yaml(self.learned_path(app), data, HEADER)
            self.drop_pending(app, card["id"])

    def add_pending(self, app: str, card: dict, reason: str) -> None:
        with _lock:
            p = _load_yaml(self.pending_path(app), {"cards": []})
            p["cards"] = [x for x in p["cards"] if x["card"]["id"] != card["id"]] + [{"reason": reason, "card": card}]
            _save_yaml(self.pending_path(app), p, HEADER)

    def drop_pending(self, app: str, card_id: str) -> bool:
        with _lock:
            path = self.pending_path(app)
            p = _load_yaml(path, {"cards": []})
            n = len(p["cards"])
            p["cards"] = [x for x in p["cards"] if x["card"]["id"] != card_id]
            if len(p["cards"]) != n:
                _save_yaml(path, p, HEADER)
            return len(p["cards"]) != n

    def remove_card(self, app: str, card_id: str) -> bool:
        with _lock:
            data = self.learned(app)
            n = len(data["cards"])
            data["cards"] = [c for c in data["cards"] if c["id"] != card_id]
            removed = len(data["cards"]) != n or data.get("extends", {}).pop(card_id, None) is not None
            if removed:
                _save_yaml(self.learned_path(app), data, HEADER)
            return removed or self.drop_pending(app, card_id)

    # ---- notes ----------------------------------------------------------------------------
    def notes(self) -> list[dict]:
        return _load_yaml(self.notes_path, {"notes": []}).get("notes", [])

    def add_note(self, app: str, topic: str, fact: str, cite: str) -> str:
        """'added' or 'merged' (same idea already known: only the citation is added)."""
        with _lock:
            data = _load_yaml(self.notes_path, {"notes": []})
            notes = data["notes"]
            f = fold(fact)
            for n in notes:
                if n["app"] == app and fuzz.token_set_ratio(fold(n["fact"]), f) >= 85:
                    if cite not in n["sources"]:
                        n["sources"] = (n["sources"] + [cite])[-5:]
                    _save_yaml(self.notes_path, data, HEADER)
                    return "merged"
            nid = f"n{int(time.time() * 1000) % 10**10}"
            notes.append({"id": nid, "app": app, "topic": topic.strip()[:80], "fact": fact.strip()[:400],
                          "sources": [cite]})
            per_app = [n for n in notes if n["app"] == app]
            if len(per_app) > MAX_NOTES_PER_APP:  # keep memory small: drop the least cited, oldest first
                victim = min(per_app, key=lambda n: (len(n["sources"]), n["id"]))
                notes.remove(victim)
            data["notes"] = sorted(notes, key=lambda n: (n["app"], fold(n["topic"])))
            _save_yaml(self.notes_path, data, HEADER)
            return "added"

    def remove_note(self, note_id: str) -> bool:
        with _lock:
            data = _load_yaml(self.notes_path, {"notes": []})
            n = len(data["notes"])
            data["notes"] = [x for x in data["notes"] if x["id"] != note_id]
            if len(data["notes"]) != n:
                _save_yaml(self.notes_path, data, HEADER)
            return len(data["notes"]) != n

    # ---- log ------------------------------------------------------------------------------
    def log(self) -> list[dict]:
        return json.loads(self.log_path.read_text(encoding="utf-8")) if self.log_path.exists() else []

    def add_log(self, entry: dict) -> None:
        with _lock:
            entries = [e for e in self.log() if e.get("sha") != entry.get("sha") or not entry.get("sha")]
            entries.insert(0, entry)
            self.log_path.write_text(json.dumps(entries[:300], ensure_ascii=False, indent=1), encoding="utf-8")

    def seen(self, sha: str) -> dict | None:
        return next((e for e in self.log() if sha and e.get("sha") == sha), None)

    def overview(self) -> dict:
        apps = {}
        for app in APPS:
            d = self.learned(app)
            pend = _load_yaml(self.pending_path(app), {"cards": []})["cards"]
            apps[app] = {
                "cards": [{"id": c["id"], "title": c["title"], "source": c.get("learned", {}).get("source", "")}
                          for c in d["cards"]],
                "extends": sum(len(v) for v in d.get("extends", {}).values()),
                "pending": [{"id": x["card"]["id"], "title": x["card"]["title"], "reason": x["reason"]} for x in pend],
            }
        notes = self.notes()
        return {"apps": apps, "notes": len(notes), "recent_notes": notes[-8:][::-1], "sources": self.log()[:50]}
