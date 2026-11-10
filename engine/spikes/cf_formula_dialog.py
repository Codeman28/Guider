"""Spike 10/11/2026: walk Home → Conditional Formatting → New Rule… and dump the New Formatting Rule dialog,
to write the "tô màu cả hàng theo điều kiện" card (highlight whole rows where a column equals a value).
Run with the machine left alone; it opens and closes its own Excel."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from kem_engine.env import runtime

runtime.init()
from kem_engine.sandbox import excel, office  # noqa: E402
from kem_engine.uia import actuator  # noqa: E402
from kem_engine.uia.snapshot import snapshot  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / ".out" / "cf_dialog.json"


def find(h, name, types=None, timeout=6.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        els, _ = snapshot(office.sandbox_windows(h))
        for e in els:
            if e.name.rstrip(".…") == name.rstrip(".…") and (types is None or e.control_type in types) and e.enabled:
                return e
        time.sleep(0.3)
    raise SystemExit(f"not found: {name}")


fx = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "vocab_types.json").read_text(encoding="utf-8"))
h = office.setup(excel.SPEC, None, fixture=fx)
try:
    office.select(h, "A2:G11")
    actuator.perform("select_ribbon_tab", find(h, "Home", {"TabItem"}))
    time.sleep(0.5)
    actuator.perform("expand", find(h, "Conditional Formatting"))
    time.sleep(0.8)
    actuator.perform("select_item", find(h, "New Rule..."))
    time.sleep(2.5)
    def dump_dialog(tag):
        els, _ = snapshot(office.dialogs(h))
        print("----", tag)
        for e in els:
            if e.name or e.control_type in ("Edit", "List"):
                print(e.control_type, "|", e.name[:70], "|", e.automation_id, "|", ",".join(sorted(e.patterns)))
        return els

    actuator.perform("select_item", find(h, "► Use a formula to determine which cells to format", {"ListItem"}))
    time.sleep(1.0)
    els = dump_dialog("after Use a formula")
    edit = next(e for e in els if e.control_type == "Edit")
    actuator.perform("set_value", edit, '=$B2="adj"')
    time.sleep(0.5)
    actuator.perform("invoke", find(h, "Format...", {"Button"}))
    time.sleep(2.5)
    from kem_engine.grounding.grounder import ground
    from kem_engine.models import Target, Within
    from kem_engine.env import win32
    actuator.perform("select_ribbon_tab", find(h, "Fill", {"TabItem"}))
    time.sleep(0.8)
    actuator.perform("select_item", find(h, "Yellow", {"ListItem"}))
    time.sleep(0.5)
    els, _ = snapshot(office.dialogs(h))
    g = ground(Target(names=["OK"], control_type="Button", within=Within(names=["Format Cells"], control_type="Window")), "invoke", els)
    print("FC OK ->", g.element.rect)
    actuator.perform("invoke", g.element)
    for k in range(6):
        time.sleep(0.5)
        d = office.dialogs(h)
        print("t", k, "dialogs", [(x, win32.class_name(x), win32.window_text(x)) for x in d])
    els, _ = snapshot(office.dialogs(h) or [h.hwnd])
    for e in els:
        if e.control_type in ("Button", "Window"): print("EL", e.control_type, e.name, e.enabled, e.rect)
    raise SystemExit(0)
    actuator.perform("select_ribbon_tab", find(h, "Fill", {"TabItem"}))
    time.sleep(1.0)
    els = dump_dialog("Fill tab")
    dlg = office.dialogs(h)
    els, _ = snapshot(dlg)
    dump = [e.public() | {"patterns": sorted(e.patterns)} for e in els if e.name or e.control_type in ("Edit", "List")]
    OUT.write_text(json.dumps(dump, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(dump), "elements ->", OUT)
    for e in dump:
        print(e["control_type"], "|", e["name"][:70], "|", e["automation_id"], "|", ",".join(e["patterns"]))
finally:
    print(office.teardown(h), file=sys.stderr)
