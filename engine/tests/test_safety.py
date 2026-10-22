import pytest

from kem_engine.safety.guard import Blocklist, GuardContext, SafetyGuard, SafetyViolation

SANDBOX, POPUP, OTHER = 100, 101, 999


def guard(fg=SANDBOX, bl=None):
    ctx = GuardContext(allowed_hwnds=lambda: {SANDBOX, POPUP}, foreground=lambda: fg)
    return SafetyGuard(ctx, bl)


def test_allows_sandbox_element(make_el):
    guard().check("invoke", make_el(1, "PivotTable", "Button", root=SANDBOX))
    guard().check("expand", make_el(1, "Tables", "MenuItem", root=POPUP))


def test_rejects_unknown_intent(make_el):
    with pytest.raises(SafetyViolation, match="not allowed"):
        guard().check("delete_file", make_el(1, "x", "Button"))


def test_select_range_is_com_only(make_el):
    with pytest.raises(SafetyViolation):
        guard().check("select_range", None)


def test_rejects_element_outside_sandbox(make_el):
    with pytest.raises(SafetyViolation, match="outside"):
        guard().check("invoke", make_el(1, "OK", "Button", root=OTHER))


@pytest.mark.parametrize("name", ["File", "Share", "Save As", "Sign in", "Copilot", "Tài khoản",
                                  "Export", "Macros", "Microsoft search"])
def test_blocklisted_names(make_el, name):
    with pytest.raises(SafetyViolation, match="blocked"):
        guard().check("invoke", make_el(1, name, "Button"))


@pytest.mark.parametrize("aid", ["MeControlWidget", "FileSave", "AutoSaveSwitch", "TellMeControlAnchor"])
def test_blocklisted_automation_ids(make_el, aid):
    with pytest.raises(SafetyViolation, match="automation_id"):
        guard().check("invoke", make_el(1, "harmless", "Button", aid=aid))


def test_blocklisted_prefix(make_el):
    with pytest.raises(SafetyViolation, match="prefix"):
        guard().check("invoke", make_el(1, "Share with people", "Button"))


def test_input_intent_requires_sandbox_foreground():
    guard(fg=POPUP).check("type_text", None)
    with pytest.raises(SafetyViolation, match="foreground"):
        guard(fg=OTHER).check("key_combo", None)


def test_non_input_intent_ignores_foreground(make_el):
    guard(fg=OTHER).check("invoke", make_el(1, "OK", "Button"))


def test_wait_for_without_element():
    guard().check("wait_for", None)


def test_custom_blocklist_and_empty_name(make_el):
    bl = Blocklist(frozenset(), frozenset({"danger"}), ())
    g = guard(bl=bl)
    g.check("invoke", make_el(1, "", "Button"))
    with pytest.raises(SafetyViolation):
        g.check("invoke", make_el(1, "Danger...", "Button"))


def test_blocklist_load_from_empty_file(tmp_path):
    p = tmp_path / "b.yaml"
    p.write_text("", encoding="utf-8")
    bl = Blocklist.load(p)
    assert bl.blocks(__import__("tests.conftest", fromlist=["el"]).el(1, "File", "Button")) is None
