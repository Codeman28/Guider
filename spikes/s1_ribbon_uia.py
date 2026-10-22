"""S1: Can pywinauto (uia) see Excel M365 ribbon buttons with Name/rect/patterns? How fast?

Pass: list buttons in the Insert tab in < 1.5 s.
"""
import time

from _common import close_sandbox, open_sandbox, save_json, set_dpi_awareness

dpi_mode = set_dpi_awareness()

from pywinauto import Desktop  # noqa: E402  (after DPI awareness)

INSERT = ("Insert", "Chèn")
PATTERNS = ("invoke", "toggle", "expand_collapse", "selection_item", "value")


def patterns_of(info_el):
    el = info_el.element_info.element
    found = []
    for pid, name in ((10000, "Invoke"), (10015, "Toggle"), (10005, "ExpandCollapse"),
                      (10010, "SelectionItem"), (10002, "Value")):
        try:
            if el.GetCurrentPattern(pid):
                found.append(name)
        except Exception:
            pass
    return found


def find_ribbon_tab(win, names):
    for t in win.descendants(control_type="TabItem"):
        if t.element_info.name in names:
            return t
    return None


def fast_scan(hwnd):
    """One FindAll over the window with a CacheRequest (raw UIA via comtypes)."""
    from pywinauto.uia_defines import IUIA
    iuia = IUIA()
    uia, mod = iuia.iuia, iuia.UIA_dll
    t0 = time.perf_counter()
    cr = uia.CreateCacheRequest()
    for prop in (mod.UIA_NamePropertyId, mod.UIA_ControlTypePropertyId,
                 mod.UIA_AutomationIdPropertyId, mod.UIA_BoundingRectanglePropertyId,
                 mod.UIA_IsOffscreenPropertyId, mod.UIA_IsEnabledPropertyId,
                 mod.UIA_AccessKeyPropertyId, mod.UIA_IsInvokePatternAvailablePropertyId,
                 mod.UIA_IsExpandCollapsePatternAvailablePropertyId):
        cr.AddProperty(prop)
    root = uia.ElementFromHandle(hwnd)
    types = [mod.UIA_ButtonControlTypeId, mod.UIA_SplitButtonControlTypeId,
             mod.UIA_MenuItemControlTypeId, mod.UIA_TabItemControlTypeId,
             mod.UIA_CheckBoxControlTypeId, mod.UIA_GroupControlTypeId]
    conds = [uia.CreatePropertyCondition(mod.UIA_ControlTypePropertyId, t) for t in types]
    cond = uia.CreateAndCondition(
        uia.CreateOrConditionFromArray(conds),
        uia.CreatePropertyCondition(mod.UIA_IsOffscreenPropertyId, False))
    arr = root.FindAllBuildCache(mod.TreeScope_Descendants, cond, cr)
    items = []
    for i in range(arr.Length):
        e = arr.GetElement(i)
        r = e.CachedBoundingRectangle
        items.append((e.CachedName, e.CachedControlType, e.CachedAutomationId,
                      (r.left, r.top, r.right, r.bottom), e.CachedAccessKey))
    dt = time.perf_counter() - t0
    return {"seconds": round(dt, 3), "n": len(items),
            "has_tables_menu": any(i[0] in ("Tables", "Bảng") for i in items)}


def main():
    out = {"dpi_awareness": dpi_mode}
    sb = open_sandbox("excel")
    try:
        win = Desktop(backend="uia").window(handle=sb.hwnd).wrapper_object()

        t0 = time.perf_counter()
        tabs = [t.element_info.name for t in win.descendants(control_type="TabItem")]
        out["list_tabs_s"] = round(time.perf_counter() - t0, 3)
        out["tabs"] = tabs

        tab = find_ribbon_tab(win, INSERT)
        out["insert_tab_found"] = tab is not None
        if tab is None:
            return out
        tab.select()
        time.sleep(0.8)

        # Lower ribbon: look for the ribbon pane holding groups, then walk buttons.
        t0 = time.perf_counter()
        groups = [g for g in win.descendants(control_type="Group")]
        out["find_groups_s"] = round(time.perf_counter() - t0, 3)

        t0 = time.perf_counter()
        buttons = []
        for g in groups:
            gname = g.element_info.name
            for b in g.descendants():
                ct = b.element_info.control_type
                if ct not in ("Button", "SplitButton", "MenuItem", "CheckBox"):
                    continue
                r = b.element_info.rectangle
                buttons.append({
                    "group": gname, "name": b.element_info.name, "control_type": ct,
                    "automation_id": b.element_info.automation_id,
                    "rect": [r.left, r.top, r.right, r.bottom],
                    "offscreen": b.element_info.element.CurrentIsOffscreen,
                })
        out["walk_buttons_s"] = round(time.perf_counter() - t0, 3)

        # Patterns + key props on a few named targets
        t0 = time.perf_counter()
        detail = []
        for g in groups:
            for b in g.descendants():
                n = b.element_info.name
                if n in ("PivotTable", "Table", "Bảng", "Recommended Charts", "Biểu đồ Đề xuất"):
                    el = b.element_info.element
                    detail.append({
                        "name": n, "control_type": b.element_info.control_type,
                        "patterns": patterns_of(b),
                        "access_key": el.CurrentAccessKey, "accel_key": el.CurrentAcceleratorKey,
                        "help": el.CurrentHelpText,
                    })
        out["detail_s"] = round(time.perf_counter() - t0, 3)

        out["fast"] = fast_scan(sb.hwnd)
        out["n_groups"] = len(groups)
        out["n_buttons"] = len(buttons)
        out["groups"] = sorted({b["group"] for b in buttons})
        out["sample_buttons"] = buttons[:40]
        out["detail"] = detail
        out["total_insert_scan_s"] = round(out["find_groups_s"] + out["walk_buttons_s"], 3)
        out["pass_pywinauto_naive"] = out["n_buttons"] > 0 and out["total_insert_scan_s"] < 1.5
        out["pass"] = out["fast"]["n"] > 0 and out["fast"]["seconds"] < 1.5
        return out
    finally:
        close_sandbox(sb)


if __name__ == "__main__":
    r = main()
    save_json("s1_ribbon_uia", r)
    print({k: v for k, v in r.items() if k not in ("sample_buttons",)})
