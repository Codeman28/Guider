"""Actuator (SPEC §6.8): UIA patterns only in Phase 1 — no real mouse, no keyboard.

S4: patterns work while the sandbox is in the background, but Office brings its window to the
foreground after each ribbon command. The orchestrator warns the user up front instead of promising
side-by-side work.
"""
from __future__ import annotations

from .element import Element


class ActionError(Exception):
    pass


def _wrap(el: Element):
    from pywinauto.controls.uiawrapper import UIAWrapper
    from pywinauto.uia_element_info import UIAElementInfo
    return UIAWrapper(UIAElementInfo(el.raw))


def perform(intent: str, el: Element, value: str | None = None) -> None:
    w = _wrap(el)
    try:
        if intent in ("select_ribbon_tab", "select_item"):
            if "SelectionItem" in el.patterns:
                w.select()
            else:
                w.invoke()
        elif intent == "invoke":
            if "Invoke" in el.patterns:
                w.invoke()
            elif "ExpandCollapse" in el.patterns:
                w.expand()
            else:
                raise ActionError(f"{el.name!r} supports neither Invoke nor ExpandCollapse")
        elif intent == "expand":
            w.expand()
        elif intent == "toggle":
            w.toggle()
        elif intent == "set_value":
            if value is None:
                raise ActionError("set_value needs a value")
            w.iface_value.SetValue(value)
        else:
            raise ActionError(f"intent {intent!r} not supported by the Phase 1 actuator")
    except ActionError:
        raise
    except Exception as e:
        raise ActionError(f"{intent} on {el.name!r} failed: {e!r}") from e


def is_selected(el: Element) -> bool:
    try:
        return bool(_wrap(el).is_selected())
    except Exception:
        return False


def is_expanded(el: Element) -> bool:
    try:
        return _wrap(el).get_expand_state() == 1
    except Exception:
        return False
