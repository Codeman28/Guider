"""SafetyGuard (SPEC §8). Called before EVERY action. Pure logic — window state is injected."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from ..grounding.grounder import normalize
from ..uia.element import Element

BLOCKLIST_PATH = Path(__file__).with_name("blocklist.yaml")

ALLOWED_INTENTS = {"select_ribbon_tab", "invoke", "expand", "select_item", "toggle", "set_value",
                   "type_text", "key_combo", "type_formula", "wait_for"}
INPUT_INTENTS = {"type_text", "key_combo", "type_formula"}  # SendInput → goes to the foreground window


class SafetyViolation(Exception):
    pass


@dataclass
class Blocklist:
    automation_ids: frozenset[str]
    names: frozenset[str]
    name_prefixes: tuple[str, ...]

    @classmethod
    def load(cls, path: Path = BLOCKLIST_PATH) -> "Blocklist":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(frozenset(data.get("automation_ids", [])),
                   frozenset(normalize(n) for n in data.get("names", [])),
                   tuple(normalize(n) for n in data.get("name_prefixes", [])))

    def blocks(self, el: Element) -> str | None:
        if el.automation_id and el.automation_id in self.automation_ids:
            return f"automation_id {el.automation_id}"
        n = normalize(el.name)
        if n in self.names:
            return f"name {el.name!r}"
        for p in self.name_prefixes:
            if n.startswith(p):
                return f"name prefix {p!r}"
        return None


@dataclass
class GuardContext:
    allowed_hwnds: Callable[[], set[int]]  # sandbox window + its own popups/dialogs (§8, S3)
    foreground: Callable[[], int]


class SafetyGuard:
    def __init__(self, ctx: GuardContext, blocklist: Blocklist | None = None):
        self.ctx = ctx
        self.blocklist = blocklist or Blocklist.load()

    def check(self, intent: str, element: Element | None) -> None:
        if intent not in ALLOWED_INTENTS:
            raise SafetyViolation(f"intent {intent!r} is not allowed for UI actions")
        allowed = self.ctx.allowed_hwnds()
        if element is not None:
            if element.root_hwnd not in allowed:
                raise SafetyViolation(f"element {element.name!r} is outside the sandbox windows")
            why = self.blocklist.blocks(element)
            if why:
                raise SafetyViolation(f"blocked element ({why})")
        if intent in INPUT_INTENTS and self.ctx.foreground() not in allowed:
            raise SafetyViolation("foreground window is not the sandbox; refusing to send input")
