"""One cached FindAll per whitelisted window (S1: 0.41 s vs 0.7–1.8 s walking with pywinauto)."""
from __future__ import annotations

import time

from ..models import Rect
from .element import Element

# Elements that identify the signed-in person are dropped at the source: they never reach
# grounding, traces or any LLM payload (SPEC §6.7, §7.3). Rect kept separately for redaction.
IDENTITY_AUTOMATION_IDS = {"MeControlWidget"}

CONTROL_TYPES = ("Button", "SplitButton", "MenuItem", "TabItem", "CheckBox", "Group", "ListItem",
                 "Edit", "RadioButton", "ComboBox", "Menu", "List", "Window")

_uia = None


def _iuia():
    global _uia
    if _uia is None:
        from pywinauto.uia_defines import IUIA
        _uia = IUIA()
    return _uia


def _type_maps():
    mod = _iuia().UIA_dll
    by_id = {getattr(mod, f"UIA_{t}ControlTypeId"): t for t in CONTROL_TYPES}
    return mod, by_id


def snapshot(hwnds: list[int]) -> tuple[list[Element], list[Rect]]:
    """Return (elements, identity_rects). identity_rects = where the account widget sits, for redaction."""
    iu = _iuia()
    uia = iu.iuia
    mod, by_id = _type_maps()
    cr = uia.CreateCacheRequest()
    for p in ("Name", "ControlType", "AutomationId", "BoundingRectangle", "IsOffscreen", "IsEnabled",
              "AccessKey", "AcceleratorKey", "IsInvokePatternAvailable",
              "IsExpandCollapsePatternAvailable", "IsSelectionItemPatternAvailable",
              "IsTogglePatternAvailable", "IsValuePatternAvailable"):
        cr.AddProperty(getattr(mod, f"UIA_{p}PropertyId"))
    cond = uia.CreateAndCondition(
        uia.CreateOrConditionFromArray(
            [uia.CreatePropertyCondition(mod.UIA_ControlTypePropertyId, t) for t in by_id]),
        uia.CreatePropertyCondition(mod.UIA_IsOffscreenPropertyId, False))
    elements: list[Element] = []
    identity: list[Rect] = []
    eid = 0
    for hwnd in hwnds:
        try:
            root = uia.ElementFromHandle(hwnd)
            arr = root.FindAllBuildCache(mod.TreeScope_Descendants, cond, cr)
        except Exception:
            continue  # window vanished between enumeration and query
        for i in range(arr.Length):
            e = arr.GetElement(i)
            r = e.CachedBoundingRectangle
            rect = Rect(left=r.left, top=r.top, right=r.right, bottom=r.bottom)
            aid = e.CachedAutomationId or ""
            if aid in IDENTITY_AUTOMATION_IDS:
                identity.append(rect)
                continue
            if rect.width <= 0 or rect.height <= 0:
                continue
            pats = set()
            for label, prop in (("Invoke", "IsInvokePatternAvailable"),
                                ("ExpandCollapse", "IsExpandCollapsePatternAvailable"),
                                ("SelectionItem", "IsSelectionItemPatternAvailable"),
                                ("Toggle", "IsTogglePatternAvailable"),
                                ("Value", "IsValuePatternAvailable")):
                if e.GetCachedPropertyValue(getattr(mod, f"UIA_{prop}PropertyId")):
                    pats.add(label)
            eid += 1
            elements.append(Element(
                eid=eid, name=e.CachedName or "", control_type=by_id.get(e.CachedControlType, "?"),
                automation_id=aid, rect=rect, root_hwnd=hwnd, access_key=e.CachedAccessKey or "",
                accel_key=e.CachedAcceleratorKey or "", patterns=frozenset(pats),
                enabled=bool(e.CachedIsEnabled), raw=e))
    return elements, identity


def timed_snapshot(hwnds: list[int]):
    t0 = time.perf_counter()
    els, ident = snapshot(hwnds)
    return els, ident, time.perf_counter() - t0
