from kem_engine.grounding.grounder import (expand_names, ground, load_aliases, name_score, normalize)
from kem_engine.models import Target, Within

ALIASES = [{"insert", "chèn"}, {"tables", "bảng"}]


def test_normalize_strips_bidi_ellipsis_case():
    assert normalize("‪Book1‬  -  Excel") == "book1 - excel"
    assert normalize("Greater Than...") == "greater than"
    assert normalize("More…") == "more"
    assert normalize("") == ""


def test_expand_names_uses_alias_groups():
    assert expand_names(["Chèn"], ALIASES) == {"chèn", "insert"}
    assert expand_names(["Data"], ALIASES) == {"data"}


def test_name_score_empty_name_is_zero():
    assert name_score("", {"x"}) == 0.0


def test_tab_by_name_and_alias(insert_ribbon):
    r = ground(Target(names=["Chèn"], control_type="TabItem"), "select_ribbon_tab", insert_ribbon, ALIASES)
    assert r.element.automation_id == "TabInsert" and r.score == 100 and not r.ambiguous


def test_automation_id_wins_over_name(insert_ribbon):
    r = ground(Target(names=["nonsense"], control_type="TabItem", automation_id="TabHome"),
               "select_ribbon_tab", insert_ribbon, ALIASES)
    assert r.element.name == "Home"


def test_invoke_prefers_child_button_with_invoke_pattern(insert_ribbon):
    t = Target(names=["PivotTable"], control_type="Button|SplitButton",
               within=Within(names=["Tables"], control_type="Group"))
    r = ground(t, "invoke", insert_ribbon, ALIASES)
    assert r.element.eid == 5 and not r.ambiguous


def test_expand_prefers_split_button(insert_ribbon):
    t = Target(names=["PivotTable"], control_type="Button|SplitButton")
    r = ground(t, "expand", insert_ribbon, ALIASES)
    assert r.element.eid == 4


def test_within_restricts_to_group(insert_ribbon):
    t = Target(names=["PivotChart"], control_type="Button",
               within=Within(names=["Tables"], control_type="Group"))
    r = ground(t, "invoke", insert_ribbon, ALIASES)
    # PivotChart is outside the Tables group: no element inside → falls back to the full pool
    assert r.element is None or r.element.eid == 9


def test_disabled_elements_are_ignored(make_el):
    els = [make_el(1, "OK", "Button", patterns=["Invoke"], enabled=False)]
    r = ground(Target(names=["OK"], control_type="Button"), "invoke", els, ALIASES)
    assert r.element is None and r.repair is None


def test_collapsed_group_proposes_expand_repair(make_el):
    els = [make_el(1, "Insert", "TabItem", patterns=["SelectionItem"]),
           make_el(2, "Tables", "MenuItem", (10, 100, 80, 220), patterns=["ExpandCollapse"])]
    t = Target(names=["PivotTable"], control_type="Button|SplitButton",
               within=Within(names=["Bảng"], control_type="Group"))
    r = ground(t, "invoke", els, ALIASES)
    assert r.element is None
    assert r.repair.intent == "expand" and r.repair.element.eid == 2


def test_no_repair_without_within(make_el):
    r = ground(Target(names=["PivotTable"], control_type="Button"), "invoke",
               [make_el(1, "Tables", "MenuItem", patterns=["ExpandCollapse"])], ALIASES)
    assert r.element is None and r.repair is None


def test_low_score_not_selected(make_el):
    r = ground(Target(names=["PivotTable"], control_type="Button"), "invoke",
               [make_el(1, "Pivot", "Button", patterns=["Invoke"])], ALIASES)
    assert r.element is None and r.candidates


def test_ambiguous_when_close_rival(make_el):
    els = [make_el(1, "Insert Row", "Button", (0, 0, 10, 10), patterns=["Invoke"]),
           make_el(2, "Insert Rows", "Button", (20, 0, 30, 10), patterns=["Invoke"])]
    r = ground(Target(names=["Insert Row"], control_type="Button"), "invoke", els, ALIASES)
    assert r.element.eid == 1 and r.ambiguous


def test_ambiguous_when_same_name_elsewhere(make_el):
    # "Recommended Charts" appears twice on the Insert tab with different AccessKeys (S1)
    els = [make_el(1, "Recommended Charts", "Button", (0, 0, 10, 10), patterns=["Invoke"]),
           make_el(2, "Recommended Charts", "Button", (50, 0, 60, 10), patterns=["Invoke"])]
    r = ground(Target(names=["Recommended Charts"], control_type="Button"), "invoke", els, ALIASES)
    assert r.ambiguous


def test_shipped_aliases_load():
    groups = load_aliases()
    assert any("insert" in g and "chèn" in g for g in groups)


def test_control_type_variants_from_small_models(insert_ribbon):
    from kem_engine.grounding.grounder import canonical_type
    assert canonical_type("list_item") == "ListItem" and canonical_type("Tab Item") == "TabItem"
    r = ground(Target(names=["Insert"], control_type="tab"), "select_ribbon_tab", insert_ribbon, ALIASES)
    assert r.element.automation_id == "TabInsert"
    r = ground(Target(names=["PivotTable"], control_type="button"), "invoke", insert_ribbon, ALIASES)
    assert r.element.eid == 5
