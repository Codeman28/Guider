"""Phase 1 Writer: deterministic Vietnamese text from the Trace (no LLM).

Rules shared with the future LLM Writer (SPEC §6.10, ADR-7): bold labels are exact UIA names from the
Trace; shortcuts only from UIA AccessKey; no step that is not in the Trace; no "see image" without one.
"""
from __future__ import annotations

import re

from ..models import EnvProfile, Trace, TraceStep, Tutorial, TutorialStep

LANG_LABEL = {"en-US": "giao diện tiếng Anh", "vi-VN": "giao diện tiếng Việt"}
_BIDI = re.compile("[‎‏‪-‮]")


def clean(name: str) -> str:
    return _BIDI.sub("", name or "").strip()


def _label(name: str) -> str:
    return "**" + clean(name) + "**"


def _texts(s: TraceStep) -> tuple[str, str]:
    n = _label(s.element_name or "")
    ct = s.control_type or ""
    if s.intent == "select_ribbon_tab":
        return f"Mở thẻ {n}", f"Trên thanh ribbon, nhấn vào thẻ {n}."
    if s.intent == "expand":
        if s.inserted_reason:
            return (f"Mở nhóm {n}",
                    f"Cửa sổ Excel của bạn đang hẹp nên nhóm {n} được thu gọn thành một nút. Nhấn {n} để mở nhóm.")
        if ct == "MenuItem" and s.plan_step_id:
            return f"Mở {n}", f"Nhấn {n} để mở danh sách lựa chọn."
        return f"Mở {n}", f"Nhấn {n}."
    if s.intent == "invoke":
        if ct == "Button" and (s.element_name or "").strip().upper() == "OK":
            return f"Nhấn {n}", f"Kiểm tra lại các lựa chọn trong hộp thoại rồi nhấn {n}."
        return f"Nhấn {n}", f"Nhấn {n}."
    if s.intent == "select_item":
        return f"Chọn {n}", f"Chọn {n} trong danh sách."
    if s.intent == "toggle":
        return f"Bật {n}", f"Nhấn {n} để bật hoặc tắt."
    if s.intent == "set_value":
        return (f"Nhập giá trị vào ô {n}", f"Gõ “{s.value}” vào ô {n}.")
    return f"{s.intent} {n}", f"Thực hiện {s.intent} với {n}."


def env_label(env: EnvProfile) -> str:
    return f"Chụp trên Excel của bạn · build {env.office_build} · {LANG_LABEL.get(env.ui_lang, env.ui_lang)}"


def write(trace: Trace, title: str, tutorial_id: str, status: str) -> Tutorial:
    steps: list[TutorialStep] = []
    for i, s in enumerate(trace.steps, start=1):
        heading, body = _texts(s)
        if not s.verified:
            body = ("Bước này Guider chưa làm mẫu được trên máy bạn. " + body)
        tip = f"Phím tắt: {s.access_key}." if s.access_key else None
        if s.image is None and s.result_image is None:
            body = body.replace("theo hình", "")
        steps.append(TutorialStep(id=i, heading=f"Bước {i}: {heading}", body=body, tip=tip,
                                  image=s.image if s.verified else None,
                                  result_image=s.result_image if s.verified else None,
                                  demonstrated=s.verified))
    intro = ("Hướng dẫn này được Guider làm mẫu ngay trên Excel trong Microsoft 365 của bạn, "
             "nên các nút trong ảnh giống hệt những gì bạn đang thấy.")
    outro = {"ok": "Xong. Bạn có thể làm lại các bước trên với dữ liệu của mình.",
             "partial": "Guider chưa làm mẫu được hết các bước; phần còn lại được mô tả bằng chữ.",
             "failed": "Guider chưa làm mẫu được tác vụ này trên máy bạn.",
             "cancelled": "Bạn đã dừng phiên làm mẫu."}[status]
    return Tutorial(tutorial_id=tutorial_id, title=title, intro=intro, steps=steps, outro=outro,
                    env_label=env_label(trace.env), status=status)


def bold_labels(text: str) -> list[str]:
    return re.findall(r"\*\*(.+?)\*\*", text)


def validate_labels(tut: Tutorial, trace: Trace) -> list[str]:
    """Every bold string must be a real element name from the Trace (SPEC §6.10). Returns offenders."""
    names = {clean(s.element_name or "") for s in trace.steps}
    bad = []
    for st in tut.steps:
        for part in (st.heading, st.body, st.tip or ""):
            bad += [b for b in bold_labels(part) if b not in names]
    return bad
