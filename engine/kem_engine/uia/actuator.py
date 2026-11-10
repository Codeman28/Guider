"""Actuator (SPEC §6.8): UIA patterns only in Phase 1 — no real mouse, no keyboard.

S4: patterns work while the sandbox is in the background, but Office brings its window to the
foreground after each ribbon command. The orchestrator warns the user up front instead of promising
side-by-side work.
"""
from __future__ import annotations

import threading
import time

from .element import Element

MODAL_WAIT = 2.5  # an Invoke still running after this has opened a modal dialog (it returns when that closes)


class ActionError(Exception):
    pass


def _wrap(el: Element):
    from pywinauto.controls.uiawrapper import UIAWrapper
    from pywinauto.uia_element_info import UIAElementInfo
    return UIAWrapper(UIAElementInfo(el.raw))


def _invoke(w) -> None:
    """UIA Invoke on a button that opens a modal dialog (Data Validation..., Goal Seek...) does not return until
    the dialog closes, so the demonstration would wait forever. Run it on its own thread and move on once it
    has had time to open the dialog; errors raised quickly are still reported."""
    done, err = threading.Event(), []

    def run():
        import pythoncom
        pythoncom.CoInitializeEx(0)  # same apartment as the UIA stack
        try:
            w.invoke()
        except Exception as e:
            err.append(e)
        finally:
            done.set()

    threading.Thread(target=run, name="uia-invoke", daemon=True).start()
    if done.wait(MODAL_WAIT) and err:
        raise err[0]


def opens_dialog(el: Element) -> bool:
    """Office names every command that opens a dialog with a trailing ellipsis: "Data Validation...", "More Rules..."."""
    return el.name.rstrip().endswith(("...", "…"))


def _click(el: Element) -> None:
    from ..env import keyboard, win32
    pid = win32.window_pid(el.root_hwnd)
    if win32.window_pid(keyboard.user32.GetForegroundWindow()) != pid:  # a ribbon flyout of ours is in front:
        keyboard.bring_to_front(el.root_hwnd)                            # raising the frame would close it
    r = el.rect
    # a split button's arrow is on the right (small) or at the bottom (large): aim at the body, not the middle
    fx = 0.3 if el.control_type == "SplitButton" else 0.5
    keyboard.click(r.left + round((r.right - r.left) * fx), r.top + round((r.bottom - r.top) * fx), pid)


def _type_into(el: Element, value: str) -> None:
    """An edit box without the Value pattern (the formula box of New Formatting Rule, 10/11/2026): click into it,
    select what is there, type the text. Keys go out only while a window of the sandbox process is in front."""
    from ..env import keyboard, win32
    pid = win32.window_pid(el.root_hwnd)

    def ours():
        if win32.window_pid(keyboard.user32.GetForegroundWindow()) != pid:
            raise ActionError("cửa sổ mẫu không còn ở trước, không gõ phím")

    _click(el)
    time.sleep(0.25)
    ours()
    keyboard.press("Ctrl+A")
    keyboard.type_text(value, check_foreground=ours)
    time.sleep(0.2)


def perform(intent: str, el: Element, value: str | None = None) -> None:
    w = _wrap(el)
    try:
        if intent in ("select_item", "invoke") and opens_dialog(el):
            _click(el)  # UIA Invoke would block until the dialog closes
            return
        if intent in ("select_ribbon_tab", "select_item"):
            if "SelectionItem" in el.patterns:
                w.select()
            else:
                _invoke(w)
        elif intent == "invoke":
            if "Invoke" in el.patterns:
                _invoke(w)
            elif "ExpandCollapse" in el.patterns:
                w.expand()
            elif "Toggle" in el.patterns:  # Word/PowerPoint Bold, Italic, Center… are toggle-only buttons
                w.toggle()
            else:
                raise ActionError(f"{el.name!r} supports neither Invoke, ExpandCollapse nor Toggle")
        elif intent == "expand":
            w.expand()
        elif intent == "toggle":
            w.toggle()
        elif intent == "set_value":
            if value is None:
                raise ActionError("set_value needs a value")
            if "Value" in el.patterns:
                w.iface_value.SetValue(value)
            else:
                _type_into(el, value)
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
