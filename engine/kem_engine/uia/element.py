"""Flat UIA element record (SPEC §6.5). Pure data so Grounder/Safety are testable without Windows."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import Rect


@dataclass
class Element:
    eid: int
    name: str
    control_type: str
    automation_id: str
    rect: Rect
    root_hwnd: int  # whitelisted window whose subtree this element came from
    access_key: str = ""
    accel_key: str = ""
    patterns: frozenset[str] = frozenset()
    enabled: bool = True
    raw: Any = field(default=None, repr=False, compare=False)  # IUIAutomationElement, never serialized

    def public(self) -> dict:
        r = self.rect
        return {"eid": self.eid, "name": self.name, "control_type": self.control_type,
                "automation_id": self.automation_id, "rect": [r.left, r.top, r.right, r.bottom]}
