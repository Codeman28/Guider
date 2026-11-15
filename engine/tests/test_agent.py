"""Observe-act agent (ADR-0007): turning the model's choice into a safe step, tidying the path, learning it."""
from __future__ import annotations

from types import SimpleNamespace

from kem_engine.agent.loop import Agent, Decision, card_from_trace
from kem_engine.models import Rect, TraceStep
from kem_engine.uia.element import Element


def el(eid, name, ct, root=1, aid=""):
    return Element(eid, name, ct, aid, Rect(left=0, top=0, right=10, bottom=10), root, patterns=frozenset({"Invoke"}))


def agent(app="excel", shown=None):
    a = Agent("goal", app)
    a.shown = shown or {}
    a.main_hwnd = 1
    return a


def test_click_uses_the_listed_control_and_its_automation_id():
    a = agent(shown={7: el(7, "Format", "MenuItem", aid="FormatCellsMenu"), 8: el(8, "Format", "Button")})
    st = a.to_step(Decision(action="click", id=7, expect="menu"), 1)
    assert st.intent == "expand" and st.target.automation_id == "FormatCellsMenu"
    assert st.expected.type == "expanded"


def test_a_tab_stays_a_tab_even_when_the_model_says_menu():
    a = agent(shown={1: el(1, "Insert", "TabItem")})
    st = a.to_step(Decision(action="click", id=1, expect="menu"), 1)
    assert st.intent == "select_ribbon_tab" and st.expected.type == "tab_selected"


def test_excel_shortcuts_need_a_cell_and_alt_sequences_are_refused():
    a = agent()
    assert a.to_step(Decision(action="keys", value="Ctrl+Space"), 1) is None and "cell" in a.reject
    st = a.to_step(Decision(action="keys", value="Ctrl+Space", cell="D1"), 1)
    assert st.intent == "key_combo" and st.target.names == ["D1"]
    assert a.to_step(Decision(action="keys", value="Ctrl+Z"), 1) is not None  # does not depend on the selection
    assert agent("word").to_step(Decision(action="keys", value="Alt,H,O"), 1) is None


def test_typing_and_selecting_in_each_app():
    st = agent().to_step(Decision(action="type", cell="E2:E21", value="=C2*D2"), 1)
    assert st.intent == "type_formula" and st.expected.prop == "cell.formula_ok" and st.expected.ref == "E2"
    st = agent("powerpoint").to_step(Decision(action="type", cell="s4.1", value="Kết luận"), 1)
    assert st.intent == "type_text" and st.target.names == ["s4.1"]
    st = agent("word").to_step(Decision(action="select", cell="p2-p4"), 1)
    assert st.intent == "select_range" and st.target.names == ["p2-p4"]


def test_ribbon_boxes_get_enter_and_dialog_boxes_get_tab():
    a = agent(shown={1: el(1, "Font Size", "ComboBox", root=1), 2: el(2, "Size:", "Edit", root=99)})
    assert a.to_step(Decision(action="set_value", id=1, value="20"), 1).value == "20\n"
    assert a.to_step(Decision(action="set_value", id=2, value="20"), 1).value == "20\t"


def test_change_note_shows_the_new_lines():
    assert Agent.change_note("a\nb", "a\nb") == "file không thay đổi"
    assert Agent.change_note("A1=x | B1=y", "A1=x | B1=y | C1=z").startswith("file thay đổi: A1=x | B1=y | C1=z")


def ts(i, intent, name=None, value=None, verified=True, ct=None):
    return TraceStep(id=i, plan_step_id=None, intent=intent, element_name=name, value=value, verified=verified,
                     control_type=ct)


def test_path_tidy_drops_reselections_and_undone_steps():
    from kem_engine.orchestrator.session import Session
    s = Session.__new__(Session)
    s.trace = SimpleNamespace(steps=[ts(1, "select_range", "A1"), ts(2, "select_range", "D1:D21"),
                                     ts(3, "invoke", "Insert", ct="SplitButton"), ts(4, "key_combo", value="Ctrl+Z"),
                                     ts(5, "select_range", "D1:D21"), ts(6, "invoke", "Insert Sheet Columns"),
                                     ts(7, "select_range", "Z9")])
    s._compact_selections(0)
    assert [(x.intent, x.element_name or x.value) for x in s.trace.steps] == [
        ("select_range", "D1:D21"), ("invoke", "Insert Sheet Columns")]
    assert s.agent_path_cleaned and [x.id for x in s.trace.steps] == [1, 2]


def test_the_path_that_worked_becomes_a_card():
    trace = SimpleNamespace(steps=[ts(1, "select_range", "s3"), ts(2, "key_combo", "Ctrl+M", "Ctrl+M"),
                                   ts(3, "type_text", "Kết luận", "Kết luận"), ts(4, "invoke", "Bad", verified=False)])
    card = card_from_trace("Thêm slide Kết luận ở cuối", "powerpoint", trace, "ppt_deck_basic")
    assert card["id"].startswith("agent_them_slide") and card["title"].startswith("Cách thêm slide")
    assert [s["intent"] for s in card["steps"]] == ["select_range", "key_combo", "type_text"]
    assert card["steps"][2]["value"] == "Kết luận" and card["fixture_id"] == "ppt_deck_basic"
