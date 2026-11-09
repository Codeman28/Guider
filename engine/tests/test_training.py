"""ADR-0004 training area: grounding on the real ribbon, compact memory, sources."""
import zipfile

import pytest
import yaml

from kem_engine.intent import knowledge
from kem_engine.training import extract, sources
from kem_engine.training.extract import XStep, XTask, build_card, signature
from kem_engine.training.memory import Memory


def task(steps, app="word", title="Cách gạch ngang chữ trong Word", selection="body"):
    return XTask(app=app, title=title, keywords=["gạch ngang chữ", "strikethrough"], selection=selection,
                 steps=[XStep(**s) for s in steps])


def test_card_uses_exact_ribbon_names():
    card, why = build_card(task([
        {"intent": "select_ribbon_tab", "names": ["home"], "control_type": "TabItem"},
        {"intent": "invoke", "names": ["strike through", "Gạch ngang"], "control_type": "Button"},
    ]), "Sách A", "trang 3")
    assert why == ""
    assert card["steps"][0]["target"]["names"][0] == "Home"
    assert card["steps"][1]["target"]["names"][0] == "Strikethrough"
    assert card["steps"][1]["target"]["automation_id"] == "Strikethrough"
    assert card["preconditions"] == [{"type": "select_range", "ref": "p3"}]
    assert card["learned"] == {"source": "Sách A", "where": "trang 3", "names_checked": True}


def test_invented_ribbon_button_is_rejected():
    card, why = build_card(task([
        {"intent": "select_ribbon_tab", "names": ["Home"], "control_type": "TabItem"},
        {"intent": "invoke", "names": ["Magic Rainbow Text"], "control_type": "Button"},
    ]), "Sách A", "trang 3")
    assert card is None and "Magic Rainbow Text" in why


def test_menu_items_left_to_the_demonstration():
    card, _ = build_card(task([
        {"intent": "select_ribbon_tab", "names": ["Layout"], "control_type": "TabItem"},
        {"intent": "expand", "names": ["Margins"], "control_type": "MenuItem"},
        {"intent": "select_item", "names": ["Narrow Margins"], "control_type": "ListItem"},
    ], title="Cách thu hẹp lề"), "Sách A", "trang 9")
    assert card["steps"][1]["expected"] == {"type": "expanded"}
    assert card["steps"][2]["target"]["names"] == ["Narrow Margins"]
    assert card["learned"]["names_checked"] is False


def test_first_step_must_pick_a_tab():
    card, why = build_card(task([{"intent": "invoke", "names": ["Bold"], "control_type": "Button"}]), "S", "p")
    assert card is None


def _strike_card():
    card, _ = build_card(task([
        {"intent": "select_ribbon_tab", "names": ["Home"], "control_type": "TabItem"},
        {"intent": "invoke", "names": ["Strikethrough"], "control_type": "Button"},
    ]), "Sách A", "trang 3")
    return card


def test_same_steps_as_base_card_only_adds_phrasings(tmp_path):
    (tmp_path / "word.cards.yaml").write_text(yaml.safe_dump({"version": 1, "app": "word", "cards": [
        {"id": "word_strikethrough", "title": "Gạch ngang", "keywords": ["gạch ngang"], "steps": _strike_card()["steps"]}
    ]}, allow_unicode=True), encoding="utf-8")
    m = Memory(tmp_path)
    card = _strike_card()
    assert m.find_same(card, "word") == ("base", "word_strikethrough")
    m.merge_keywords("word", "base", "word_strikethrough", ["gạch xoá chữ", "Gạch ngang"])
    assert m.learned("word")["extends"] == {"word_strikethrough": ["gạch xoá chữ", "Gạch ngang"]}


def test_learned_cards_and_extends_load_into_the_pack(tmp_path, monkeypatch):
    base = yaml.safe_load((knowledge.KNOWLEDGE_DIR / "word.cards.yaml").read_text(encoding="utf-8"))
    (tmp_path / "word.cards.yaml").write_text(yaml.safe_dump(base, allow_unicode=True), encoding="utf-8")
    m = Memory(tmp_path)
    new = _strike_card()
    new["steps"][1]["target"]["names"] = ["Subscript"]
    new["id"], new["title"] = "learn_wor_subscript", "Cách viết chỉ số dưới"
    m.add_card("word", new)
    m.merge_keywords("word", "base", "word_bold", ["tô đậm chữ"])
    monkeypatch.setattr(knowledge, "KNOWLEDGE_DIR", tmp_path)
    pack = knowledge.KnowledgePack("word")
    assert "learn_wor_subscript" in pack.by_id
    assert "tô đậm chữ" in pack.by_id["word_bold"].keywords
    assert pack.by_id["learn_wor_subscript"].to_plan().steps[1].target.names == ["Subscript"]


def test_notes_merge_same_idea_and_keep_citations(tmp_path):
    m = Memory(tmp_path)
    assert m.add_note("excel", "Freeze", "Freeze Top Row giữ dòng đầu khi cuộn xuống.", "Sách A · trang 2") == "added"
    assert m.add_note("excel", "Cố định", "Freeze Top Row giữ dòng đầu khi cuộn xuống", "web · x") == "merged"
    assert m.notes()[0]["sources"] == ["Sách A · trang 2", "web · x"]


def test_signature_ignores_title():
    a, b = _strike_card(), _strike_card()
    b["title"] = "khác"
    assert signature(a) == signature(b)


def test_read_docx_and_relevance(tmp_path):
    p = tmp_path / "giao_trinh.docx"
    body = "".join(f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>" for t in [
        "Bài 3: Định dạng", "Chọn ô cần định dạng, nhấn tab Home, chọn Bold để in đậm chữ trong Excel.",
        "Trong hộp thoại Format Cells, chọn tab Font rồi nhấn OK."])
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
           f"{body}</w:body></w:document>")
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", xml)
    src = sources.read_file(p, 4000)
    assert src.name == "giao_trinh.docx" and src.chunks and sources.relevant(src.chunks[0].text)
    assert not sources.relevant("Lịch sử Việt Nam thế kỷ XV có nhiều biến động.")


def test_rejects_unknown_file_type(tmp_path):
    f = tmp_path / "a.exe"
    f.write_bytes(b"x")
    with pytest.raises(ValueError):
        sources.read_file(f, 4000)


def test_link_must_be_http():
    with pytest.raises(ValueError):
        sources.fetch_url("file:///C:/Windows/win.ini", 4000)


def test_group_named_as_a_step_becomes_within():
    card, why = build_card(task([
        {"intent": "select_ribbon_tab", "names": ["Home"], "control_type": "TabItem"},
        {"intent": "invoke", "names": ["Font"], "control_type": "Button"},
        {"intent": "invoke", "names": ["Superscript"], "control_type": "Button"},
    ], title="Cách viết chỉ số trên"), "Sách", "trang 1")
    assert why == "" and [s["target"]["names"][0] for s in card["steps"]] == ["Home", "Superscript"]
    assert card["steps"][1]["target"]["within"] == {"names": ["Font"], "control_type": "Group"}
    assert [s["id"] for s in card["steps"]] == [1, 2]


def test_pacer_keeps_requests_under_the_minute_limit(monkeypatch):
    from kem_engine.training import llm as tllm
    clock = {"t": 0.0}
    slept = []
    monkeypatch.setattr(tllm.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(tllm.time, "sleep", lambda d: (slept.append(d), clock.__setitem__("t", clock["t"] + d)))
    p = tllm._Pacer(3)
    for _ in range(4):
        p.wait()
    assert len(slept) == 1 and 59 < slept[0] <= 60.1  # the 4th start waited for the window


def test_compact_pending_merges_same_steps_and_known_cards(tmp_path):
    (tmp_path / "word.cards.yaml").write_text(yaml.safe_dump({"version": 1, "app": "word", "cards": [
        {"id": "word_strikethrough", "title": "Gạch ngang", "keywords": ["gạch ngang"], "steps": _strike_card()["steps"]}
    ]}, allow_unicode=True), encoding="utf-8")
    m = Memory(tmp_path)
    known = _strike_card()
    a = _strike_card()
    a["steps"][1]["target"]["names"] = ["Subscript"]
    a["id"], a["keywords"] = "a", ["chỉ số dưới"]
    b = dict(a, id="b", title="Viết chỉ số dưới", keywords=["số nhỏ dưới chân"])
    for c in (known, a, b):
        m.add_pending("word", c, "chưa chạy thử")
    r = m.compact_pending("word")
    assert r == {"before": 3, "after": 1, "merged_known": 1, "merged_dup": 1}
    left = m.pending("word")[0]["card"]
    assert "số nhỏ dưới chân" in left["keywords"] and "chỉ số dưới" in left["keywords"]
    assert "word_strikethrough" in m.learned("word")["extends"]


def test_windows_shortcuts_never_become_cards():
    from kem_engine.env.keyboard import KeyComboError, parse_combo
    for combo in ("Ctrl+Esc", "Alt+Tab", "Alt+F4", "Ctrl+Shift+Esc"):
        with pytest.raises(KeyComboError):
            parse_combo(combo)
    assert parse_combo("Ctrl+Shift+L") == [0x11, 0x10, ord("L")]
    st, why = extract.key_step(XStep(intent="key_combo", names=["Ctrl+Esc"], control_type="Keys", value="Ctrl+Esc"), "excel", 1, True)
    assert st is None and "Windows" in why


def _formula_card(cell="E2", formula="=D2-C2"):
    return {"id": "learn_exc_tru", "title": "Cách trừ hai cột", "keywords": ["trừ"], "fixture_id": "sales_table_basic",
            "steps": [{"id": 1, "intent": "type_formula", "target": {"names": [cell], "control_type": "Cell"},
                       "value": formula, "expected": {"type": "com_check", "prop": "cell.formula_ok", "ref": cell,
                                                      "op": "true"}, "capture_result": True}]}


class _Lab:
    """Pretends to be Excel: a formula works on the fixtures listed in `ok`."""
    def __init__(self, ok):
        self.ok, self.tried = ok, []

    def run(self, fx, steps):
        self.tried.append(fx["id"])
        good = fx["id"] in self.ok
        return good, [f"{c}={'12' if good else '#VALUE!'}" for c, _ in steps]


def test_formula_moves_to_the_first_sample_file_that_computes_it():
    from kem_engine.training import refit
    lab = _Lab({"numbers_grid", "grades_basic"})
    card, fx, why = refit.refit_formula(lab, None, _formula_card())
    assert fx is None and card["fixture_id"] == "numbers_grid" and "numbers_grid" in why
    assert lab.tried[0] == "sales_table_basic"  # the card's own file is tried first


def test_built_fixture_is_kept_only_when_excel_computes_it():
    from kem_engine.training import refit

    class LLM:
        def complete(self, system, user, out, max_tokens=0):
            return out(columns=["Giá", "Giảm"], rows=[[100, 10]], steps=[{"cell": "C2", "formula": "=A2-B2"}],
                       example="Ô C2 cho 90.")

    class Lab(_Lab):
        def run(self, fx, steps):
            return fx["id"].startswith("card_"), ["C2=90"]

    card, fx, why = refit.refit_formula(Lab(set()), LLM(), _formula_card())
    assert fx["id"] == card["fixture_id"] == "card_learn_exc_tru"
    assert card["steps"][0]["value"] == "=A2-B2" and card["steps"][0]["expected"]["ref"] == "C2"
    assert card["example"] == "Ô C2 cho 90."


def test_missing_button_takes_the_closest_name_on_screen():
    from kem_engine.training import refit
    card = {"id": "c", "title": "Nhóm dữ liệu", "steps": [
        {"id": 1, "intent": "select_ribbon_tab", "target": {"names": ["Data"], "control_type": "TabItem"}},
        {"id": 2, "intent": "expand", "target": {"names": ["Group..."], "control_type": "SplitButton"}}]}
    seen = {"want": "Group...", "seen": ["Group|SplitButton", "Ungroup|SplitButton", "Data|TabItem"]}
    fixed, how = refit.repair_names(None, card, seen)
    assert fixed["steps"][1]["target"]["names"][:2] == ["Group", "Group..."] and "Group" in how
    assert refit.repair_names(None, card, {"want": "Group...", "seen": ["Sort|Button"]})[0] is None


def test_model_cannot_pick_a_name_that_is_not_on_screen():
    from kem_engine.training import refit

    class LLM:
        def complete(self, system, user, out, max_tokens=0):
            return out(pick="Magic Button", open_first=None)

    card = {"id": "c", "title": "Đổ bóng chữ", "steps": [
        {"id": 1, "intent": "invoke", "target": {"names": ["Shadow"], "control_type": "Button"}}]}
    assert refit.repair_names(LLM(), card, {"want": "Shadow", "seen": ["Bold|Button"]})[0] is None


def test_card_fixture_ids_resolve_only_inside_the_cards_folder(tmp_path, monkeypatch):
    from kem_engine.sandbox import office
    monkeypatch.setattr(office, "FIXTURES", tmp_path)
    (tmp_path / "cards").mkdir()
    (tmp_path / "cards" / "card_x.json").write_text('{"id": "card_x", "columns": [], "rows": []}', encoding="utf-8")
    assert office.load_fixture("card_x")["id"] == "card_x"
    with pytest.raises(ValueError):
        office.load_fixture("card_../../secret")


def test_vietnamese_separators_become_commas_outside_text():
    from kem_engine.training.refit import en_separators
    assert en_separators('=ROUND(D2; -1)') == "=ROUND(D2, -1)"
    assert en_separators('=IF(A1>0; "a;b"; 0)') == '=IF(A1>0, "a;b", 0)'
