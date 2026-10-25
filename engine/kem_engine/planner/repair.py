"""Repair a plan the model wrote before anything is clicked ('tăng cỡ chữ' planned as
Page Layout → 'Page Layout' → …, so nothing after step 1 could be shown).

Against the real ribbon of the app:
- a tab step snaps to the real tab name;
- a group caption used as a step ("Font", "Paragraph") becomes the `within` of the next step;
- a ribbon button is looked up on the current tab, then on every tab — when it lives elsewhere, the right tab is
  selected first; names, control type and AutomationId come from the ribbon, not from the model;
- a ribbon-level step whose button exists nowhere is dropped;
- steps inside a menu/gallery that was opened, or inside a dialog, are kept: the demonstration decides.
"""
from __future__ import annotations

import structlog

from ..intent.ribbon import find_control, find_tab, is_group, ribbon
from ..models import Plan, Step, Target, Within

log = structlog.get_logger()

DIALOG_CLOSERS = {"OK", "CANCEL", "CLOSE", "APPLY", "ĐÓNG", "HỦY", "HUỶ"}


def _opens_dialog(name: str, step: Step) -> bool:
    return name.rstrip().endswith("...") or name.rstrip().endswith("…") or step.expected.type == "dialog_opened"


def repair(plan: Plan) -> tuple[Plan, list[str]]:
    app = plan.app
    if not ribbon(app):
        return plan, []
    notes: list[str] = []
    out: list[Step] = []
    tab: str | None = None
    ctx = "ribbon"  # ribbon | menu | dialog
    group: str | None = None
    steps = plan.steps
    for k, s in enumerate(steps):
        names = list(s.target.names) if s.target else []
        first = names[0].strip() if names else ""
        if s.intent == "select_ribbon_tab":
            real = find_tab(app, names)
            if real is None:
                notes.append(f"bỏ tab không có thật: {first}")
                continue
            if not (real == tab and ctx == "ribbon"):
                out.append(Step(id=0, intent="select_ribbon_tab", expected={"type": "tab_selected"},
                                target=Target(names=[real] + [n for n in names if n != real], control_type="TabItem")))
            tab, ctx = real, "ribbon"
            continue
        if ctx == "dialog" or not s.target:
            out.append(s.model_copy(update={"id": 0}))
            if first.upper() in DIALOG_CLOSERS:
                ctx = "ribbon"
            continue
        if ctx == "menu":
            out.append(s.model_copy(update={"id": 0}))
            ctx = "menu" if s.intent == "expand" else ("dialog" if _opens_dialog(first, s) else "ribbon")
            continue
        # ribbon level
        if is_group(first) and k + 1 < len(steps) and steps[k + 1].intent != "select_ribbon_tab":
            group = first.rstrip(".").strip()
            notes.append(f"'{group}' là tên nhóm, không phải nút")
            continue
        hit = find_control(app, names, tab)
        if hit is None:
            if s.intent == "select_item":  # a gallery item shown on the ribbon (e.g. transitions): let it try
                out.append(s.model_copy(update={"id": 0}))
                continue
            notes.append(f"bỏ nút không có trên ribbon: {first}")
            continue
        real_tab, row = hit
        if real_tab != tab:
            notes.append(f"'{row['name']}' nằm ở tab {real_tab}")
            out.append(Step(id=0, intent="select_ribbon_tab", target=Target(names=[real_tab], control_type="TabItem"),
                            expected={"type": "tab_selected"}))
            tab = real_tab
        ct, intent = row["ct"], s.intent
        if ct == "SplitButton" and intent == "expand":
            ct = "SplitButton|MenuItem"
        if ct == "ComboBox" and intent not in ("set_value", "expand"):
            intent = "set_value" if s.value else "expand"
        within = Within(names=[group], control_type="Group") if group else s.target.within
        target = Target(names=[row["name"]] + [n for n in names if n != row["name"]], control_type=ct,
                        automation_id=row.get("aid") or None, within=within)
        out.append(s.model_copy(update={"id": 0, "intent": intent, "target": target}))
        group = None
        ctx = "menu" if intent == "expand" else ("dialog" if _opens_dialog(row["name"], s) else "ribbon")
    fixed = [st.model_copy(update={"id": i}) for i, st in enumerate(out, start=1)]
    if notes:
        log.info("planner.repaired", notes=notes)
    return plan.model_copy(update={"steps": fixed}), notes
