"""Phase 1 Writer: deterministic Vietnamese text from the Trace (no LLM).

Rules shared with the future LLM Writer (SPEC §6.10, ADR-7): bold labels are exact UIA names from the
Trace; shortcuts only from UIA AccessKey; no step that is not in the Trace; no "see image" without one.
"""
from __future__ import annotations

import re

from ..models import EnvProfile, Trace, TraceStep, Tutorial, TutorialExample, TutorialStep

LANG_LABEL = {"en-US": "giao diện tiếng Anh", "vi-VN": "giao diện tiếng Việt"}
APP_NAME = {"excel": "Excel", "word": "Word", "powerpoint": "PowerPoint"}
_BIDI = re.compile("[‎‏‪-‮]")


def clean(name: str) -> str:
    return _BIDI.sub("", name or "").strip()


def _label(name: str) -> str:
    n = clean(name)
    return f"**{n}**" if n else "nút cần dùng"  # never bold an empty string


def _texts(s: TraceStep, app: str = "Excel") -> tuple[str, str]:
    n = _label(s.element_name or "")
    ct = s.control_type or ""
    if s.intent == "select_ribbon_tab":
        return f"Mở thẻ {n}", f"Trên thanh ribbon, nhấn vào thẻ {n}."
    if s.intent == "expand":
        if s.inserted_reason:
            return (f"Mở nhóm {n}",
                    f"Cửa sổ {app} của bạn đang hẹp nên nhóm {n} được thu gọn thành một nút. Nhấn {n} để mở nhóm.")
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
    if s.intent == "type_formula":
        if ":" in (s.element_name or ""):
            return (f"Gõ công thức cho vùng {n}", f"Chọn vùng {n}, gõ “{s.value}” rồi nhấn Ctrl+Enter để điền cả vùng.")
        return (f"Gõ công thức vào ô {n}", f"Chọn ô {n}, gõ “{s.value}” rồi nhấn Enter.")
    if s.intent == "select_range":
        what = f"vùng {n}" if ":" in (s.element_name or "") else f"ô {n}"
        return (f"Chọn {what}", f"Kéo chuột (hoặc giữ Shift và dùng phím mũi tên) để chọn {what}.")
    if s.intent == "key_combo":
        if "+" in (s.element_name or "").strip("+"):
            return (f"Nhấn {n}", f"Nhấn tổ hợp phím {n}: giữ các phím đầu, rồi nhấn phím cuối.")
        return (f"Nhấn phím {n}", f"Nhấn phím {n}.")
    return f"{s.intent} {n}", f"Thực hiện {s.intent} với {n}."


def env_label(env: EnvProfile, user_file: bool = False) -> str:
    where = "bản sao file của bạn" if user_file else f"{APP_NAME.get(env.app, env.app)} của bạn"
    return f"Chụp trên {where}, build {env.office_build}, {LANG_LABEL.get(env.ui_lang, env.ui_lang)}"


SAMPLE_DATA = {  # what the fixtures contain (engine/fixtures), for the worked example
    "excel": "bảng doanh số mẫu gồm 4 cột Tháng, Khu vực, Sản phẩm, Doanh số (20 dòng)",
    "word": "bản báo cáo mẫu 6 đoạn (đoạn 1 là tiêu đề, đoạn 2 và 4 là đề mục)",
    "powerpoint": "bài thuyết trình mẫu 3 slide (slide 1 tiêu đề, slide 2–3 có tiêu đề và các ý gạch đầu dòng)",
}


def _selection_text(ref: str, app: str, user_file: bool) -> str:
    if user_file:
        return {"excel": "vùng dữ liệu đang dùng trong file", "word": "đoạn văn cần làm",
                "powerpoint": "slide cần làm"}.get(app, "phần cần làm")
    if app == "excel":
        return f"vùng {ref}" if ":" in ref else f"ô {ref}"
    if app == "word":
        if ref == "all":
            return "toàn bộ văn bản"
        a, _, b = ref.partition("-")
        return f"đoạn {a[1:]}" if not b else f"đoạn {a[1:]} đến {b[1:]}"
    slide, _, shape = ref[1:].partition(".")
    return f"slide {slide}" if not shape else ("tiêu đề" if shape == "1" else "nội dung") + f" của slide {slide}"


def example(trace: Trace) -> TutorialExample | None:
    """'Ví dụ' section: the demonstration itself, told as a concrete case, with its final screenshot."""
    done = [s for s in trace.steps if s.verified and s.element_name]
    if not done:
        return None
    app = trace.env.app
    image = trace.final_image or next((s.result_image or s.image for s in reversed(done)
                                       if s.result_image or s.image), None)
    if trace.example:
        own = trace.example.replace("**", "").strip().removeprefix("Ví dụ:").strip()  # bold = trace names only
        return TutorialExample(text="Ví dụ: " + own, image=image)
    data = "bản sao file của bạn" if trace.user_file else SAMPLE_DATA.get(app, "file mẫu")
    sel = ", ".join(_selection_text(r, app, trace.user_file) for r in trace.selection)
    labels = [_label(s.element_name or "") for s in done if s.intent != "select_ribbon_tab"]
    tab = next((_label(s.element_name or "") for s in done if s.intent == "select_ribbon_tab"), None)
    clicks = ", rồi ".join(labels) if labels else ""
    text = f"Ví dụ: trên {data}" + (f", chọn {sel}" if sel else "") + (f", mở thẻ {tab}" if tab else "")
    text += (f", nhấn {clicks}." if clicks else ".")
    text += (" Ảnh dưới là kết quả sau cùng; bạn làm y hệt trên dữ liệu của mình." if trace.final_image
             else " Kết quả như ảnh dưới đây; bạn làm y hệt trên dữ liệu của mình." if image else "")
    return TutorialExample(text=text, image=image)


def write(trace: Trace, title: str, tutorial_id: str, status: str) -> Tutorial:
    steps: list[TutorialStep] = []
    app = APP_NAME.get(trace.env.app, trace.env.app)
    for i, s in enumerate(trace.steps, start=1):
        heading, body = _texts(s, app)
        if not s.verified:
            if s.image and "_missing" in s.image:
                body = ("Guider chưa bấm được nút này trên máy bạn; ảnh là màn hình lúc đó để bạn tự tìm. " + body)
            elif s.image:
                body = ("Guider đã bấm nhưng chưa kiểm chứng được kết quả bước này; ảnh là lúc trước khi bấm. " + body)
            else:
                body = ("Bước này Guider chưa làm mẫu được trên máy bạn. " + body)
        tip = f"Phím tắt: {s.access_key}." if s.access_key else None
        if s.image is None and s.result_image is None:
            body = body.replace("theo hình", "")
        steps.append(TutorialStep(id=i, heading=f"Bước {i}: {heading}", body=body, tip=tip,
                                  image=s.image,  # every step keeps its picture, demonstrated or not
                                  result_image=s.result_image if s.verified else None,
                                  demonstrated=s.verified))
    intro = (f"Hướng dẫn này được Guider làm mẫu ngay trên {app} trong Microsoft 365 của bạn, "
             "nên các nút trong ảnh giống hệt những gì bạn đang thấy.")
    if trace.user_file:
        intro = (f"Hướng dẫn này được Guider làm mẫu trên một bản sao file của bạn trong {app}; file gốc "
                 "không bị thay đổi. Các nút trong ảnh giống hệt những gì bạn đang thấy.")
    outro = {"ok": "Xong. Bạn có thể làm lại các bước trên với dữ liệu của mình.",
             "partial": "Guider chưa làm mẫu được hết các bước; phần còn lại được mô tả bằng chữ.",
             "failed": "Guider chưa làm mẫu được tác vụ này trên máy bạn.",
             "cancelled": "Bạn đã dừng phiên làm mẫu."}[status]
    if trace.alternative and status in ("ok", "partial"):  # keyboard-first card: the mouse way, in one line
        outro += f" Cách khác, dùng chuột: {trace.alternative}."
    return Tutorial(tutorial_id=tutorial_id, title=title, intro=intro, steps=steps, outro=outro,
                    env_label=env_label(trace.env, trace.user_file), status=status,
                    example=example(trace) if status in ("ok", "partial") else None)


_DASH = re.compile(r"\s*[—–]\s*")


def tidy(text: str) -> str:
    """House style (Hallmark polish, 26/10/2026): no em/en dashes in copy, a comma reads the same."""
    return _DASH.sub(", ", text or "").replace(", ,", ",")


def tidy_tutorial(tut: Tutorial) -> Tutorial:
    steps = [s.model_copy(update={"heading": tidy(s.heading), "body": tidy(s.body), "tip": tidy(s.tip) if s.tip else s.tip})
             for s in tut.steps]
    ex = tut.example.model_copy(update={"text": tidy(tut.example.text)}) if tut.example else None
    return tut.model_copy(update={"title": tidy(tut.title), "intro": tidy(tut.intro), "outro": tidy(tut.outro),
                                  "steps": steps, "example": ex})


def bold_labels(text: str) -> list[str]:
    return re.findall(r"\*\*(.+?)\*\*", text)


def validate_labels(tut: Tutorial, trace: Trace) -> list[str]:
    """Every bold string must be a real element name from the Trace (SPEC §6.10). Returns offenders."""
    names = {clean(s.element_name or "") for s in trace.steps}
    bad = []
    for st in tut.steps:
        for part in (st.heading, st.body, st.tip or ""):
            bad += [b for b in bold_labels(part) if b not in names]
    if tut.example:
        bad += [b for b in bold_labels(tut.example.text) if b not in names]
    return bad
