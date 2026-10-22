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


@dataclass
class Card:
    id: str
    title: str
    keywords: list[str]
    raw: dict

    def to_plan(self) -> Plan:
        r = self.raw
        return Plan(task_canonical=self.id, title=self.title, fixture_id=r.get("fixture_id"),
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
        path = path or KNOWLEDGE_DIR / f"{app}.cards.yaml"
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        self.version = f"{data.get('version', 0)}-{hashlib.sha1(text.encode()).hexdigest()[:8]}"
        self.cards = [Card(c["id"], c["title"], list(c.get("keywords", [])), c) for c in data["cards"]]
        self.by_id = {c.id: c for c in self.cards}

    def match(self, question: str, top_k: int = 3) -> list[tuple[float, Card]]:
        q = fold(question)
        scored = []
        for c in self.cards:
            best = 0.0
            for kw in c.keywords + [c.title]:
                k = fold(kw)
                if len(k) < 3:
                    continue
                if re.search(rf"(?<!\w){re.escape(k)}(?!\w)", q):
                    s = 100.0
                else:
                    s = fuzz.partial_ratio(k, q) if len(k) >= 6 else 0.0
                best = max(best, s)
            scored.append((best, c))
        scored.sort(key=lambda x: -x[0])
        return scored[:top_k]
