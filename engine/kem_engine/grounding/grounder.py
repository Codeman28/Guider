"""Deterministic Grounder (SPEC §6.5): plan step → one UIA element, without calling an LLM.

Fuzzy match on names (+ EN↔VI aliases), filtered by control type and `within`. When the target is not
on screen, propose a local repair (S1: collapsed ribbon groups are the common case, not an exception).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from rapidfuzz import fuzz

from ..models import Intent, Target
from ..uia.element import Element

THRESHOLD = 90.0
MARGIN = 10.0

PATTERN_FOR_INTENT: dict[str, str] = {
    "invoke": "Invoke", "expand": "ExpandCollapse", "select_item": "SelectionItem",
    "select_ribbon_tab": "SelectionItem", "toggle": "Toggle", "set_value": "Value",
}

_BIDI = re.compile("[‎‏‪-‮]")
ALIASES_PATH = Path(__file__).resolve().parents[2] / "knowledge" / "aliases.yaml"


_HYPHENS = re.compile("[‐-―−]")  # Office uses U+2011 in "Add‑ins"


def normalize(s: str) -> str:
    s = _HYPHENS.sub("-", _BIDI.sub("", s or "")).strip().lower()
    s = re.sub(r"(\.\.\.|…)$", "", s)
    return re.sub(r"\s+", " ", s).strip()


def load_aliases(path: Path = ALIASES_PATH) -> list[set[str]]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [{normalize(n) for n in group} for group in data.get("aliases", [])]


def expand_names(names: list[str], aliases: list[set[str]]) -> set[str]:
    out = {normalize(n) for n in names}
    for group in aliases:
        if out & group:
            out |= group
    return out


def name_score(name: str, wanted: set[str]) -> float:
    n = normalize(name)
    if not n:
        return 0.0
    return max((fuzz.ratio(n, w) for w in wanted), default=0.0)


@dataclass
class Repair:
    intent: Intent
    element: Element
    reason: str


@dataclass
class GroundResult:
    element: Element | None
    score: float = 0.0
    ambiguous: bool = False
    candidates: list[tuple[float, Element]] = field(default_factory=list)
    repair: Repair | None = None


UIA_TYPES = ("Button", "SplitButton", "MenuItem", "TabItem", "CheckBox", "Group", "ListItem", "Edit",
             "RadioButton", "ComboBox", "Menu", "List", "Window")
_TYPE_KEYS = {t.lower(): t for t in UIA_TYPES} | {"tab": "TabItem", "textbox": "Edit", "text": "Edit",
                                                  "dropdown": "ComboBox", "checkbutton": "CheckBox",
                                                  "listitem": "ListItem", "galleryitem": "ListItem"}


def canonical_type(t: str) -> str:
    """'button', 'list_item', 'Tab Item' → UIA ControlType names (S7/eval: small models vary the casing)."""
    k = re.sub(r"[\s_-]", "", t or "").lower()
    return _TYPE_KEYS.get(k, t.strip())


def _types(spec: str) -> list[str]:
    return [canonical_type(t) for t in spec.split("|") if t.strip()]


def _containers(target: Target, elements: list[Element], aliases) -> list[Element]:
    if not target.within:
        return []
    wanted = expand_names(target.within.names, aliases)
    types = _types(target.within.control_type)
    return [e for e in elements if e.control_type in types and name_score(e.name, wanted) >= THRESHOLD]


def ground(target: Target, intent: Intent, elements: list[Element],
           aliases: list[set[str]] | None = None) -> GroundResult:
    aliases = aliases if aliases is not None else load_aliases()
    types = _types(target.control_type)
    wanted = expand_names(target.names, aliases)
    pool = [e for e in elements if (e.enabled or target.allow_disabled) and e.control_type in types]

    containers = _containers(target, elements, aliases)
    if containers:  # group visible on the ribbon → only accept elements inside it
        inside = [e for e in pool if any(c.rect.contains(e.rect) and c is not e for c in containers)]
        if inside:
            pool = inside

    scored: list[tuple[float, Element]] = []
    for e in pool:
        s = 100.0 if target.automation_id and e.automation_id == target.automation_id else name_score(e.name, wanted)
        if s > 0:
            scored.append((s, e))

    need = PATTERN_FOR_INTENT.get(intent)

    def rank(item):
        s, e = item
        has_pattern = need is None or need in e.patterns
        type_rank = types.index(e.control_type) if e.control_type in types else len(types)
        return (-s, not has_pattern, type_rank, e.rect.width * e.rect.height)

    scored.sort(key=rank)
    if not scored or scored[0][0] < THRESHOLD:
        return GroundResult(None, scored[0][0] if scored else 0.0, candidates=scored[:5],
                            repair=_repair(target, intent, elements, aliases))

    best_s, best = scored[0]
    rivals = [(s, e) for s, e in scored[1:]
              if normalize(e.name) != normalize(best.name) and best_s - s < MARGIN]
    same_name_elsewhere = [e for s, e in scored[1:]
                           if normalize(e.name) == normalize(best.name) and s == best_s
                           and (need is None or need in e.patterns)
                           and not (e.rect.contains(best.rect) or best.rect.contains(e.rect))]
    return GroundResult(best, best_s, ambiguous=bool(rivals or same_name_elsewhere), candidates=scored[:5])


def _repair(target: Target, intent: Intent, elements: list[Element], aliases) -> Repair | None:
    """Target absent: maybe its ribbon group collapsed into a dropdown (S1) — expand that first."""
    if not target.within:
        return None
    wanted = expand_names(target.within.names, aliases)
    for e in elements:
        if (e.control_type in ("MenuItem", "SplitButton", "Button") and "ExpandCollapse" in e.patterns
                and name_score(e.name, wanted) >= THRESHOLD):
            return Repair("expand", e, f"nhóm '{e.name}' bị thu gọn vì ribbon hẹp")
    return None
