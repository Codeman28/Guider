"""Dump every ribbon tab's controls (name, type, AutomationId, group) on a sandbox — source for the
Knowledge Pack, so it only names buttons that really exist on this Office build."""
import json
import sys
import time

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "engine"))
from kem_engine.env import runtime  # noqa: E402

runtime.init()
from kem_engine.uia import actuator  # noqa: E402
from kem_engine.uia.snapshot import snapshot  # noqa: E402

from _common import OUT  # noqa: E402

from kem_engine.sandbox import office  # noqa: E402
from kem_engine.sandbox.registry import SPECS  # noqa: E402

APP = sys.argv[1] if len(sys.argv) > 1 else "excel"
TABS = {"excel": ["Home", "Insert", "Page Layout", "Formulas", "Data", "Review", "View"],
        "word": ["Home", "Insert", "Design", "Layout", "References", "Review", "View"],
        "powerpoint": ["Home", "Insert", "Design", "Transitions", "Animations", "Slide Show", "Review", "View"]}[APP]
FIXTURE = {"excel": "sales_table_basic", "word": "word_report_basic", "powerpoint": "ppt_deck_basic"}[APP]
sb = office.setup(SPECS[APP], FIXTURE, size_logical=(1600, 800))
out = {}
try:
    for tab in TABS:
        els, _ = snapshot([sb.hwnd])
        t = next((e for e in els if e.control_type == "TabItem" and e.name == tab), None)
        if t is None:
            print("tab not found:", tab)
            continue
        actuator.perform("select_ribbon_tab", t)
        time.sleep(0.8)
        els, _ = snapshot([sb.hwnd])
        groups = [e for e in els if e.control_type == "Group"]
        rows = []
        for e in els:
            if e.control_type in ("Group", "TabItem", "Window") or not e.name:
                continue
            if e.rect.top > t.rect.bottom + 200:  # below the ribbon
                continue
            g = next((g.name for g in groups if g.rect.contains(e.rect) and g is not e), None)
            rows.append({"name": e.name, "ct": e.control_type, "aid": e.automation_id, "group": g,
                         "key": e.access_key, "patterns": sorted(e.patterns)})
        out[tab] = rows
        print(tab, len(rows))
finally:
    office.teardown(sb)
(OUT / ("ribbon_dump.json" if APP == "excel" else f"ribbon_dump_{APP}.json")).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
