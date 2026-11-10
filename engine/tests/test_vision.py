"""Picture of the user's problem (ADR-0005): parsing what the model saw, the rebuilt sample, the card pick."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from kem_engine.intent.knowledge import KnowledgePack
from kem_engine.vision import problem as vp


def seen(**kw) -> vp.Seen:
    base = {"app": "excel", "problem": "Cột Giá báo #N/A", "task": "Cách dùng IFERROR để ẩn lỗi #N/A"}
    return vp.Seen(**{**base, **kw})


def test_table_lines_become_a_table():
    d = vp.Diagnosis.from_seen(seen(content="Mã | Tên | Giá\n|---|---|---|\nSP01 | Bút | #N/A\nSP02 | Vở | 12,000\n"))
    assert d.table.columns == ["Mã", "Tên", "Giá"]
    assert d.table.rows == [["SP01", "Bút", "#N/A"], ["SP02", "Vở", "12,000"]]


def test_short_rows_are_padded_and_long_tables_capped():
    lines = "A | B | C\n" + "\n".join(f"x{i} | {i}" for i in range(50))
    d = vp.Diagnosis.from_seen(seen(content=lines))
    assert len(d.table.rows) == vp.MAX_ROWS
    assert d.table.rows[0] == ["x0", "0", ""]


def test_word_content_is_paragraphs():
    d = vp.Diagnosis.from_seen(seen(app="word", content="Tiêu đề\n\nĐoạn một\nĐoạn hai"))
    assert d.table is None and d.paragraphs == ["Tiêu đề", "Đoạn một", "Đoạn hai"]


def test_sample_keeps_the_error_and_the_numbers():
    d = vp.Diagnosis.from_seen(seen(content="Mã | Giá | SL | Ghi chú\nSP01 | #N/A | 3 | =C2*D2\nSP02 | #DIV/0! | 012 | \n"))
    fx = vp.sample_fixture(d)
    assert fx["columns"] == ["Mã", "Giá", "SL", "Ghi chú"]
    assert fx["rows"][0] == ["SP01", "=NA()", 3, "'=C2*D2"]  # an unknown formula stays text
    assert fx["rows"][1] == ["SP02", "=1/0", "012", ""]  # leading zero: a code, not a number


def test_no_table_no_sample():
    assert vp.sample_fixture(vp.Diagnosis.from_seen(seen(content="chỉ có chữ"))) is None


def test_powerpoint_sample_is_one_slide():
    fx = vp.sample_fixture(vp.Diagnosis.from_seen(seen(app="powerpoint", content="Kế hoạch\nÝ một\nÝ hai")))
    assert fx["slides"] == [{"title": "Kế hoạch", "body": ["Ý một", "Ý hai"]}]


def test_prepare_shrinks_and_never_touches_the_original(tmp_path):
    src = tmp_path / "shot.jpg"
    Image.new("RGB", (3200, 1000), "white").save(src)
    before = src.read_bytes()
    out = vp.prepare(src, tmp_path / "work", max_side=1600)
    assert out.suffix == ".png" and Image.open(out).size == (1600, 500)
    assert src.read_bytes() == before


def test_prepare_refuses_other_files(tmp_path):
    f = tmp_path / "x.xlsx"
    f.write_bytes(b"PK")
    with pytest.raises(vp.ProblemError):
        vp.prepare(f, tmp_path / "w")


def test_pasted_data_url(tmp_path):
    import base64
    import io
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), "red").save(buf, "PNG")
    p = vp.save_pasted("data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), tmp_path)
    assert Image.open(vp.prepare(p, tmp_path)).size == (40, 20)


def test_formula_cards_keep_their_own_table():
    pack = KnowledgePack("excel")
    assert vp.needs_own_layout(pack.by_id["formula_iferror"])
    assert not vp.needs_own_layout(pack.by_id[next(c.id for c in pack.cards if "freeze" in c.id)])


def test_read_picks_a_clear_card_without_a_second_call(tmp_path, monkeypatch):
    img = tmp_path / "p.png"
    Image.new("RGB", (200, 100), "white").save(img)
    calls = []
    monkeypatch.setattr(vp, "cloud_enabled", lambda: False)
    monkeypatch.setattr(vp, "look", lambda *a, **k: vp.Diagnosis.from_seen(
        seen(task="Cách bật bộ lọc AutoFilter", problem="Không lọc được bảng")))
    monkeypatch.setattr(vp, "_ollama", lambda *a, **k: calls.append(a) or '{"choice": 0}')
    packs = {"excel": KnowledgePack("excel")}
    r = vp.read(img, "", packs.__getitem__, tmp_path / "w")
    assert r.card_id == "filter_on_keys"
    assert r.query == packs["excel"].by_id[r.card_id].title
    assert calls == []


def test_read_asks_the_model_to_choose_when_unclear(tmp_path, monkeypatch):
    img = tmp_path / "p.png"
    Image.new("RGB", (200, 100), "white").save(img)
    monkeypatch.setattr(vp, "cloud_enabled", lambda: False)
    monkeypatch.setattr(vp, "look", lambda *a, **k: vp.Diagnosis.from_seen(
        seen(task="Cách dùng hàm IFERROR để che giấu lỗi #N/A khi VLOOKUP không tìm thấy giá trị")))
    seen_menu = {}

    def fake(conf, messages, schema, timeout, max_tokens=900):
        seen_menu["text"] = messages[-1]["content"]
        assert "images" not in messages[-1]  # the pick is text only
        n = next(i for i, ln in enumerate(seen_menu["text"].splitlines()) if "IFERROR" in ln and ln[:1].isdigit())
        return json.dumps({"choice": int(seen_menu["text"].splitlines()[n].split(".")[0])})

    monkeypatch.setattr(vp, "_ollama", fake)
    r = vp.read(img, "sao lỗi", {"excel": KnowledgePack("excel")}.__getitem__, tmp_path / "w")
    assert r.card_id and "iferror" in r.card_id


def test_loose_keyword_match_still_asks_the_model(tmp_path, monkeypatch):
    img = tmp_path / "p.png"
    Image.new("RGB", (200, 100), "white").save(img)
    monkeypatch.setattr(vp, "cloud_enabled", lambda: False)
    monkeypatch.setattr(vp, "look", lambda *a, **k: vp.Diagnosis.from_seen(seen(task="Cách xóa dữ liệu trùng lặp")))
    asked = []
    monkeypatch.setattr(vp, "_ollama", lambda *a, **k: asked.append(1) or '{"choice": 0}')
    r = vp.read(img, "", {"excel": KnowledgePack("excel")}.__getitem__, tmp_path / "w")
    assert asked and r.card_id is None and r.query == "Cách xóa dữ liệu trùng lặp"


def test_model_pick_out_of_range_means_no_card(monkeypatch):
    pack = KnowledgePack("excel")
    monkeypatch.setattr(vp, "_ollama", lambda *a, **k: '{"choice": 99}')
    d = vp.Diagnosis.from_seen(seen())
    assert vp.pick_card(pack.cards[:3], d, vp.VisionConf(), 5) is None


def test_not_office_is_refused(tmp_path, monkeypatch):
    img = tmp_path / "p.png"
    Image.new("RGB", (50, 50)).save(img)
    monkeypatch.setattr(vp, "cloud_enabled", lambda: False)
    monkeypatch.setattr(vp, "look", lambda *a, **k: vp.Diagnosis.from_seen(seen(app="other")))
    with pytest.raises(vp.ProblemError, match="Office"):
        vp.read(img, "", lambda a: KnowledgePack.empty(a), tmp_path / "w")


def test_ocr_fallback_finds_the_error_value():
    d = vp.from_ocr(["Book1 - Excel", "SP01", "#DIV/O!"], "")
    assert d.app == "excel" and d.error_value == "#DIV/0!" and "#DIV/0!" in d.task
    assert vp.from_ocr(["random"], "") is None


def test_cloud_reading_is_on_by_default_with_a_key(tmp_path, monkeypatch):
    monkeypatch.setenv("KEM_SETTINGS", str(tmp_path / "settings.json"))
    key = {"saved": True}
    monkeypatch.setattr("kem_engine.llm.secrets.has_key", lambda p, path=None: key["saved"])
    assert vp.cloud_enabled() is True  # no settings file yet
    (tmp_path / "settings.json").write_text('{"provider": "ollama"}', encoding="utf-8")
    assert vp.cloud_enabled() is True
    (tmp_path / "settings.json").write_text('{"vision_cloud": false}', encoding="utf-8")
    assert vp.cloud_enabled() is False  # the user turned it off
    (tmp_path / "settings.json").write_text('{}', encoding="utf-8")
    key["saved"] = False
    assert vp.cloud_enabled() is False  # no key, no upload


def test_rpc_validates_vision_cloud(tmp_path):
    from kem_engine.rpc.server import RpcError, Server
    s = Server(lambda: None, tmp_path / "tutorials", write=lambda line: None, settings_path=tmp_path / "s.json")
    with pytest.raises(RpcError):
        s.settings_set({"vision_cloud": "yes"})
    assert s.settings_set({"vision_cloud": True})["vision_cloud"] is True


def test_problem_section_survives_export(tmp_path):
    from kem_engine.models import Tutorial, TutorialProblem
    from kem_engine.rpc.export import to_html, to_markdown
    Image.new("RGB", (10, 10)).save(tmp_path / "problem.png")
    t = Tutorial(tutorial_id="x", title="T", intro="i", steps=[], outro="o", env_label="e", status="ok",
                 problem=TutorialProblem(summary="Cột Giá báo #N/A", sample="rebuilt"))
    assert "## Vấn đề của bạn" in to_markdown(t) and "problem.png" in to_markdown(t)
    assert "Vấn đề của bạn" in to_html(t, tmp_path) and "data:image/png" in to_html(t, tmp_path)


def test_images_are_served_only_from_their_folders(tmp_path, monkeypatch):
    from kem_engine.rpc.server import RpcError, Server
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    tut = tmp_path / "t1"
    tut.mkdir()
    Image.new("RGB", (4, 4)).save(tut / "step_01.png")
    (tut / "tutorial.json").write_text("{}", encoding="utf-8")

    class Store:
        def tutorial_path(self, tid):
            return tut if tid == "t1" else None

    class Svc:
        store = Store()

    s = Server(lambda: Svc(), tmp_path / "tutorials", write=lambda line: None, settings_path=tmp_path / "s.json")
    assert s.tutorial_image({"tutorial_id": "t1", "file": "step_01.png"})["data_url"].startswith("data:image/png;base64,")
    for bad in ("../secrets.bin", r"..\x.png", "tutorial.json"):
        with pytest.raises(RpcError):
            s.tutorial_image({"tutorial_id": "t1", "file": bad})
    from kem_engine.sandbox.office import work_root
    inbox = work_root() / "inbox" / "a"
    inbox.mkdir(parents=True)
    Image.new("RGB", (4, 4)).save(inbox / "problem.png")
    assert s.problem_image({"path": str(inbox / "problem.png")})["data_url"]
    with pytest.raises(RpcError):
        s.problem_image({"path": str(tut / "step_01.png")})


def test_ok_inside_a_stacked_dialog_is_told_apart():
    from kem_engine.grounding.grounder import ground
    from kem_engine.models import Target, Within
    from kem_engine.uia.element import Element, Rect

    def el(eid, name, t, r):
        return Element(eid, name, t, "", Rect(left=r[0], top=r[1], right=r[2], bottom=r[3]), 1,
                       patterns=frozenset({"Invoke"}))

    els = [el(1, "Format Cells", "Window", (703, 0, 1395, 681)), el(2, "OK", "Button", (1136, 632, 1250, 663)),
           el(3, "New Formatting Rule", "Window", (729, 113, 1369, 574)), el(4, "OK", "Button", (1169, 535, 1257, 565))]
    fc = ground(Target(names=["OK"], control_type="Button", within=Within(names=["Format Cells"], control_type="Window")),
                "invoke", els)
    nfr = ground(Target(names=["OK"], control_type="Button",
                        within=Within(names=["New Formatting Rule"], control_type="Window")), "invoke", els)
    assert fc.element.eid == 2 and nfr.element.eid == 4
