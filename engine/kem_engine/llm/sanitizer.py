"""Payload sanitizer (SPEC §7.3) — mandatory before every cloud call.

Structural whitelist first (only known keys survive), then string scrubbing: anything that looks like
an email, a file path, a URL, a phone number or an Office window title is removed or masked.
Screenshots and document contents are never part of a payload, so they have no key to survive under.
"""
from __future__ import annotations

import re
from typing import Any

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
URL = re.compile(r"\b(?:https?|ftp|file)://\S+", re.I)
WIN_PATH = re.compile(r"(?:\b[a-zA-Z]:\\|\\\\)[^\s\"']*")
UNIX_PATH = re.compile(r"(?<![\w.])/(?:[\w.-]+/)+[\w.-]*")
PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d .-]{8,}\d)(?!\d)")
WINDOW_TITLE = re.compile(r"\s+[-–]\s+(?:Excel|Word|PowerPoint)\s*$", re.I)  # "Book1  -  Excel" (S1)

ENV_KEYS = ("app", "ui_lang", "office_build")
ELEMENT_KEYS = ("eid", "name", "control_type")
STEP_KEYS = ("id", "intent", "element_name", "control_type", "access_key", "value", "verified",
             "inserted_reason")
TOP_KEYS = {"question", "env", "elements", "ribbon_tabs", "knowledge", "steps", "step", "title", "candidates",
            "previous_output", "errors"}


def scrub(text: str) -> str:
    """Mask identity-like substrings inside free text (the user's question, plan values)."""
    text = EMAIL.sub("[email]", text)
    text = URL.sub("[url]", text)
    text = WIN_PATH.sub("[path]", text)
    text = UNIX_PATH.sub("[path]", text)
    return PHONE.sub("[số]", text)


def is_identity_label(name: str) -> bool:
    """UI labels that would carry identity: emails, paths, window titles. Such elements are dropped."""
    return bool(EMAIL.search(name) or WIN_PATH.search(name) or URL.search(name) or WINDOW_TITLE.search(name))


def _pick(d: dict, keys) -> dict:
    return {k: d[k] for k in keys if k in d}


def _elements(items: list) -> list[dict]:
    out = []
    for e in items:
        if not isinstance(e, dict) or is_identity_label(str(e.get("name", ""))):
            continue
        out.append(_pick(e, ELEMENT_KEYS))
    return out


def _step(s: dict) -> dict:
    s = _pick(s, STEP_KEYS)
    for k in ("element_name", "value", "inserted_reason"):
        if isinstance(s.get(k), str):
            s[k] = scrub(s[k])
    if isinstance(s.get("element_name"), str) and is_identity_label(s["element_name"]):
        s["element_name"] = None
    return s


def sanitize(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in payload.items():
        if key not in TOP_KEYS:
            continue
        if key in ("question", "title", "previous_output", "errors") and isinstance(val, str):
            out[key] = scrub(val)
        elif key == "env" and isinstance(val, dict):
            out[key] = _pick(val, ENV_KEYS)
        elif key in ("elements", "candidates") and isinstance(val, list):
            out[key] = _elements(val)
        elif key == "ribbon_tabs" and isinstance(val, list):
            out[key] = [str(t) for t in val if not is_identity_label(str(t))]
        elif key == "knowledge" and isinstance(val, str):
            out[key] = val  # authored by us, versioned in engine/knowledge
        elif key == "steps" and isinstance(val, list):
            out[key] = [_step(s) for s in val if isinstance(s, dict)]
        elif key == "step" and isinstance(val, dict):
            out[key] = {k: (scrub(v) if isinstance(v, str) else v) for k, v in val.items()
                        if k in ("id", "intent", "target")}
    return out
