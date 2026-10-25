"""The real ribbon of each app (from spikes/dump_ribbon.py, M365 build 20326 EN UI), shipped with the engine.

Used to check and repair plans the model writes — before anything is clicked — and by the training area:
a button the model names must exist, on the tab where it really lives.
"""
from __future__ import annotations

import json
from functools import lru_cache

from ..grounding.grounder import expand_names, load_aliases, name_score
from .knowledge import KNOWLEDGE_DIR, fold

RIBBON_DIR = KNOWLEDGE_DIR / "ribbon"
MATCH = 85.0

# Ribbon group captions (EN). Text says "in the Font group, click Bold": a group is where a button lives,
# never a step of its own. Clicking it would hit the group's dialog launcher ("Font...").
GROUPS = {fold(g) for g in (
    "Clipboard", "Font", "Paragraph", "Styles", "Editing", "Number", "Alignment", "Cells", "Slides", "Drawing",
    "Tables", "Illustrations", "Charts", "Pages", "Header & Footer", "Text", "Symbols", "Page Setup", "Links",
    "Comments", "Media", "Images", "Themes", "Variants", "Customize", "Transition to This Slide", "Timing",
    "Animation", "Advanced Animation", "Sort & Filter", "Data Tools", "Function Library", "Defined Names",
    "Formula Auditing", "Calculation", "Window", "Zoom", "Show", "Views", "Table of Contents", "Footnotes",
    "Captions", "Index", "Arrange", "Proofing", "Language", "Changes", "Tracking", "Protect", "Document Formatting",
    "Page Background", "Sparklines", "Filters", "Tours", "Macros", "Workbook Views", "Sheet Options",
    "Scale to Fit", "Get & Transform Data", "Queries & Connections", "Outline", "Forecast", "Citations & Bibliography",
    "Mail Merge", "Start Mail Merge", "Write & Insert Fields", "Preview Results", "Finish", "Set Up",
    "Start Slide Show", "Monitors", "Presentation Views", "Master Views", "Insights", "Accessibility")}


@lru_cache(maxsize=None)
def ribbon(app: str) -> dict[str, list[dict]]:
    """{tab name: [{name, ct, aid, patterns, …}]} — empty when this app has no dump."""
    path = RIBBON_DIR / f"{app}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def is_group(name: str) -> bool:
    return fold((name or "").strip().rstrip(".").strip()) in GROUPS


def find_tab(app: str, names: list[str]) -> str | None:
    wanted = expand_names([n for n in names if n], load_aliases())
    best = max(ribbon(app), key=lambda t: name_score(t, wanted), default=None)
    return best if best is not None and name_score(best, wanted) >= MATCH else None


def find_control(app: str, names: list[str], tab: str | None = None) -> tuple[str, dict] | None:
    """(tab, control) for the best match: on `tab` first, else on any tab."""
    wanted = expand_names([n for n in names if n], load_aliases())
    tabs = ribbon(app)
    order = ([tab] if tab in tabs else []) + [t for t in tabs if t != tab]
    for t in order:
        rows = [r for r in tabs[t] if r.get("name")]
        hit = max(rows, key=lambda r: name_score(r["name"], wanted), default=None)
        if hit is not None and name_score(hit["name"], wanted) >= MATCH:
            return t, hit
    return None
