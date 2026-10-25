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
