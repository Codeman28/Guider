"""Phase 1 helper: drive a hand-written flow on a sandbox, dumping new windows + matching elements.

Usage: python explore.py pivot|chart|cf
"""
import sys
import time

from _common import (class_name, close_sandbox, open_sandbox, save_json, set_dpi_awareness,
                     top_level_windows, window_rect, window_text)

set_dpi_awareness()
from pywinauto import Desktop  # noqa: E402

D = Desktop(backend="uia")

FLOWS = {
    "pivot": [("Insert", "TabItem", "select"), ("Tables", "MenuItem", "expand"),
              ("PivotTable", "Button", "invoke")],
    "chart": [("Insert", "TabItem", "select"), ("Insert Column or Bar Chart", "MenuItem", "expand")],
    "cf": [("Home", "TabItem", "select"), ("Conditional Formatting", None, "expand"),
           ("Highlight Cells Rules", None, "expand"), ("Greater Than...", None, "invoke")],
}
KEYWORDS = {"pivot": ["Pivot", "OK", "Table/Range", "New Worksheet"],
            "chart": ["Column", "Clustered"],
            "cf": ["Conditional", "Highlight", "Greater", "OK", "Format cells"]}


def find_in(hwnds, name, ct):
    for h in hwnds:
        for e in D.window(handle=h).wrapper_object().descendants():
            i = e.element_info
            if i.name == name and (ct is None or i.control_type == ct):
                return e
    raise LookupError(name)


def dump(hwnd, kws):
    out = []
    for e in D.window(handle=hwnd).wrapper_object().descendants():
        i = e.element_info
        if any(k.lower() in (i.name or "").lower() for k in kws) or i.control_type in ("Edit", "RadioButton"):
            r = i.rectangle
            out.append([i.name, i.control_type, i.automation_id, [r.left, r.top, r.right, r.bottom]])
    return out


task = sys.argv[1]
sb = open_sandbox("excel")
log = {}
try:
    ws = sb.app.ActiveSheet
    data = [("Tháng", "Khu vực", "Sản phẩm", "Doanh số")]
    for i in range(20):
        data.append((f"T{i % 6 + 1}", ["Bắc", "Trung", "Nam"][i % 3], ["A", "B", "C", "D"][i % 4], 50 + i * 7))
    ws.Range("A1:D21").Value = data
    ws.Range("A1:D21").Select()
    for name, ct, act in FLOWS[task]:
        before = set(top_level_windows(sb.pid))
        hw = [sb.hwnd] + [h for h in before if class_name(h) not in ("XLMAIN",)
                          and not class_name(h).startswith("MSO_B")]
        el = find_in(hw, name, ct)
        info = el.element_info
        getattr(el, act)()
        time.sleep(1.5)
        nw = [h for h in top_level_windows(sb.pid) if h not in before
              and not class_name(h).startswith("MSO_B")]
        log[name] = {"ct": info.control_type, "aid": info.automation_id,
                     "new_windows": [{"hwnd": h, "class": class_name(h), "title": window_text(h),
                                      "rect": window_rect(h), "hits": dump(h, KEYWORDS[task])} for h in nw],
                     "main_hits": dump(sb.hwnd, KEYWORDS[task])}
        print(name, info.control_type, info.automation_id, [(class_name(h), window_text(h)) for h in nw])
    save_json(f"explore_{task}", log)
finally:
    close_sandbox(sb)
