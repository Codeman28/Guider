from kem_engine.models import EnvProfile, Trace, TraceStep
from kem_engine.writer.template import bold_labels, env_label, validate_labels, write

ENV = EnvProfile(app="excel", office_version="16.0", office_build="20326", ui_lang="en-US", ui_lcid=1033,
                 dpi=120, scale_pct=125, screen=(1920, 1080))


def trace(*steps):
    return Trace(session_id="s", task_canonical="t", env=ENV, steps=list(steps))


def ts(i, intent, name, ct="Button", **kw):
    return TraceStep(id=i, plan_step_id=i, intent=intent, element_name=name, control_type=ct,
                     verified=kw.pop("verified", True), image=kw.pop("image", f"step_{i:02d}.png"), **kw)


def test_full_tutorial_shape_and_labels():
    tr = trace(ts(1, "select_ribbon_tab", "Insert", "TabItem", access_key="Alt, N"),
               TraceStep(id=2, plan_step_id=None, intent="expand", element_name="Tables", control_type="MenuItem",
                         inserted_reason="thu gọn", verified=True, image="step_02.png"),
               ts(3, "invoke", "PivotTable"),
               ts(4, "invoke", "OK"),
               ts(5, "set_value", "Format cells that are GREATER THAN", "Edit", value="100"),
               ts(6, "select_item", "Clustered Column", "ListItem"),
               ts(7, "toggle", "Bold"),
               ts(8, "expand", "Conditional Formatting", "MenuItem"),
               ts(9, "expand", "Something", "SplitButton"))
    tut = write(tr, "Tiêu đề", "id1", "ok")
    assert [s.heading.split(":")[0] for s in tut.steps] == [f"Bước {i}" for i in range(1, 10)]
    assert tut.steps[0].tip == "Phím tắt: Alt, N."
    assert "thu gọn" in tut.steps[1].body
    assert "“100”" in tut.steps[4].body
    assert validate_labels(tut, tr) == []
    assert tut.env_label == env_label(ENV) and "tiếng Anh" in tut.env_label


def test_bidi_marks_removed_from_labels():
    tr = trace(ts(1, "invoke", "‪Book1‬"))
    tut = write(tr, "t", "id", "ok")
    assert bold_labels(tut.steps[0].heading) == ["Book1"]
    assert validate_labels(tut, tr) == []


def test_failed_step_is_text_only():
    tr = trace(ts(1, "invoke", "PivotTable"), ts(2, "invoke", "OK", verified=False))
    tut = write(tr, "t", "id", "partial")
    assert tut.steps[1].image is None and not tut.steps[1].demonstrated
    assert tut.steps[1].body.startswith("Bước này Guider chưa làm mẫu được")
    assert "chưa làm mẫu" in tut.outro


def test_unknown_intent_and_no_image():
    tr = trace(TraceStep(id=1, plan_step_id=1, intent="wait_for", element_name="x", verified=True))
    tut = write(tr, "t", "id", "cancelled")
    assert "wait_for" in tut.steps[0].heading and "dừng" in tut.outro


def test_validate_labels_catches_invented_label():
    tr = trace(ts(1, "invoke", "PivotTable"))
    tut = write(tr, "t", "id", "failed")
    tut.steps[0].body += " Sau đó nhấn **Insert PivotTable**."
    assert validate_labels(tut, tr) == ["Insert PivotTable"]


def test_empty_name_is_never_bolded():
    tr = trace(TraceStep(id=1, plan_step_id=1, intent="select_item", element_name=None, verified=False))
    tut = write(tr, "t", "id", "partial")
    assert "****" not in tut.steps[0].heading + tut.steps[0].body
