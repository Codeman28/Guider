"""Plans the model writes are checked against the real ribbon before anything is clicked (25/10/2026)."""
from kem_engine.models import Plan, Step, Target
from kem_engine.planner.repair import repair


def plan(app, *steps):
    return Plan(task_canonical="t", title="t", app=app, steps=[
        Step(id=i, intent=it, value=v, target=Target(names=[n], control_type=ct))
        for i, (it, n, ct, v) in enumerate(steps, start=1)])


def names(p):
    return [(s.intent, s.target.names[0]) for s in p.steps]


def test_button_on_wrong_tab_gets_the_right_tab():
    fixed, notes = repair(plan("excel", ("select_ribbon_tab", "Page Layout", "TabItem", None),
                               ("invoke", "Increase Font Size", "Button", None)))
    assert names(fixed) == [("select_ribbon_tab", "Page Layout"), ("select_ribbon_tab", "Home"),
                            ("invoke", "Increase Font Size")]
    assert fixed.steps[2].target.automation_id == "FontSizeIncrease"
    assert [s.id for s in fixed.steps] == [1, 2, 3]


def test_group_caption_becomes_within_and_invented_button_is_dropped():
    fixed, notes = repair(plan("word", ("select_ribbon_tab", "home", "TabItem", None),
                               ("invoke", "Font", "Button", None),
                               ("invoke", "Superscript", "Button", None),
                               ("invoke", "Make It Pretty", "Button", None)))
    assert names(fixed) == [("select_ribbon_tab", "Home"), ("invoke", "Superscript")]
    assert fixed.steps[1].target.within.names == ["Font"]
    assert any("Make It Pretty" in n for n in notes)


def test_menu_and_dialog_steps_are_left_to_the_demonstration():
    fixed, _ = repair(plan("excel", ("select_ribbon_tab", "Home", "TabItem", None),
                           ("expand", "Conditional Formatting", "MenuItem", None),
                           ("expand", "Highlight Cells Rules", "MenuItem", None),
                           ("invoke", "Greater Than...", "MenuItem", None),
                           ("set_value", "Format cells that are GREATER THAN", "Edit", "100"),
                           ("invoke", "OK", "Button", None)))
    assert [n for _, n in names(fixed)] == ["Home", "Conditional Formatting", "Highlight Cells Rules",
                                           "Greater Than...", "Format cells that are GREATER THAN", "OK"]


def test_font_size_combobox_gets_a_value_step():
    fixed, _ = repair(plan("excel", ("select_ribbon_tab", "Home", "TabItem", None),
                           ("invoke", "Font Size", "ComboBox", "16")))
    assert fixed.steps[1].intent == "set_value" and fixed.steps[1].target.control_type == "ComboBox"
