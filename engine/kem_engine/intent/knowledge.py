"""Knowledge Pack access: task cards matched to a free-text question (VI/EN, with or without diacritics)."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml
from rapidfuzz import fuzz

from ..models import Plan

KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "knowledge"


def fold(text: str) -> str:
    """Lowercase, strip Vietnamese diacritics (đ→d), collapse spaces: 'Biểu đồ' → 'bieu do'."""
    t = (text or "").lower().replace("đ", "d")
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^\w%&+ ]", " ", t)).strip()


def _word_in(w: str, words: list[str]) -> bool:
    """Short words must match exactly ("tron" ≠ "trong"); longer ones tolerate a typo."""
    if len(w) <= 4:
        return w in words
    return any(fuzz.ratio(w, qw) >= 85 for qw in words)


@dataclass
class Card:
    id: str
    title: str
    keywords: list[str]
    raw: dict
    app: str = "excel"

    def to_plan(self) -> Plan:
        r = self.raw
        return Plan(task_canonical=self.id, title=self.title, fixture_id=r.get("fixture_id"), app=self.app,
                    preconditions=r.get("preconditions", []), steps=r["steps"],
                    success_check=r.get("success_check"))

    def summary(self) -> str:
        """Compact text for the Planner prompt."""
        parts = []
        for s in self.raw["steps"]:
            t = s.get("target") or {}
            parts.append(f"{s['intent']}({'/'.join(t.get('names', []))}:{t.get('control_type', '')})")
        return f"[{self.id}] {self.title}: " + " → ".join(parts)


class KnowledgePack:
    def __init__(self, app: str = "excel", path: Path | None = None):
        learned_path = KNOWLEDGE_DIR / f"{app}.learned.yaml" if path is None else None
        path = path or KNOWLEDGE_DIR / f"{app}.cards.yaml"
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        self.app = data.get("app", app)
        self.cards = [Card(c["id"], c["title"], list(c.get("keywords", [])), c, self.app) for c in data["cards"]]
        # Training area (ADR-0004): demonstrated cards + extra phrasings for existing cards
        if learned_path is not None and learned_path.exists():
            ltext = learned_path.read_text(encoding="utf-8")
            text += ltext
            learned = yaml.safe_load(ltext) or {}
            known = {c.id for c in self.cards}
            self.cards += [Card(c["id"], c["title"], list(c.get("keywords", [])), c, self.app)
                           for c in learned.get("cards", []) if c["id"] not in known]
            for cid, kws in (learned.get("extends") or {}).items():
                for c in self.cards:
                    if c.id == cid:
                        c.keywords += [k for k in kws if k not in c.keywords]
        self.version = f"{data.get('version', 0)}-{hashlib.sha1(text.encode()).hexdigest()[:8]}"
        self.by_id = {c.id: c for c in self.cards}

    @classmethod
    def empty(cls, app: str) -> "KnowledgePack":
        k = cls.__new__(cls)
        k.app, k.version, k.cards, k.by_id = app, "0-empty", [], {}
        return k

    def match(self, question: str, top_k: int = 3) -> list[tuple[float, Card]]:
        """100 = a keyword occurs as a phrase; 95/85 = every word of a keyword occurs in any order
        (small typos allowed on long words); 0 otherwise. Ties prefer the longer matched keyword."""
        q = fold(question)
        q_words = q.split()
        scored = []
        for c in self.cards:
            best = (0.0, 0)
            for kw in c.keywords + [c.title]:
                k = fold(kw)
                if len(k) < 3:
                    continue
                if re.search(rf"(?<!\w){re.escape(k)}(?!\w)", q):
                    s = 100.0
                elif all(_word_in(w, q_words) for w in k.split()):
                    # every word present (any order): strong when the keyword has 2+ real words
                    s = 95.0 if sum(len(w) >= 3 for w in k.split()) >= 2 else 85.0
                else:
                    continue
                best = max(best, (s, len(k)))
            scored.append((best, c))
        scored.sort(key=lambda x: (-x[0][0], -x[0][1]))
        return [(sc[0], c) for sc, c in scored[:top_k]]
