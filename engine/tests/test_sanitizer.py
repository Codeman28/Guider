from kem_engine.llm.sanitizer import is_identity_label, sanitize, scrub


def test_scrub_masks_identity_like_text():
    t = scrub("gửi cho a.b@c.com.vn, file C:\\Users\\Huy\\sales.xlsx, /home/u/x.txt, https://x.y/z, 0912 345 678")
    assert "[email]" in t and t.count("[path]") == 2 and "[url]" in t and "[số]" in t
    assert "@" not in t and "Users" not in t and "0912" not in t


def test_scrub_keeps_plain_question():
    q = "Cách tạo PivotTable trong Excel cho cột A1:D21"
    assert scrub(q) == q


def test_identity_labels():
    assert is_identity_label("\u202aBook1\u202c  -  Excel")
    assert is_identity_label("a@b.co")
    assert is_identity_label("D:\\work\\x.xlsx")
    assert is_identity_label("see https://x.y")
    assert not is_identity_label("PivotTable")


def test_whitelist_drops_unknown_keys_and_fields():
    out = sanitize({
        "question": "mail tôi ở x@y.com",
        "env": {"app": "excel", "ui_lang": "en-US", "office_build": "20326", "screen": [1920, 1080], "dpi": 120},
        "elements": [{"eid": 1, "name": "PivotTable", "control_type": "Button", "rect": [1, 2, 3, 4]},
                     {"eid": 2, "name": "Book1 - Excel", "control_type": "TitleBar"}, "junk"],
        "candidates": [{"eid": 3, "name": "OK", "control_type": "Button", "automation_id": "x"}],
        "ribbon_tabs": ["Home", "a@b.c"],
        "knowledge": "[pivot_basic] ...",
        "steps": [{"id": 1, "intent": "set_value", "element_name": "Name Box", "value": "C:\\x\\y.xlsx",
                   "verified": True, "rect": [0, 0, 1, 1]},
                  {"id": 2, "intent": "invoke", "element_name": "x@y.com"},
                  {"id": 3, "intent": "invoke", "element_name": "‪Book1‬  -  Excel"}, 7],
        "step": {"id": 1, "intent": "invoke", "target": {"names": ["OK"]}, "secret": "x"},
        "previous_output": "{\"a\": \"z@z.zz\"}",
        "errors": "bad",
        "screenshot": "base64...",
        "cell_values": [[1, 2]],
        "title": 5,
    })
    assert out["question"] == "mail tôi ở [email]"
    assert out["env"] == {"app": "excel", "ui_lang": "en-US", "office_build": "20326"}
    assert out["elements"] == [{"eid": 1, "name": "PivotTable", "control_type": "Button"}]
    assert out["candidates"] == [{"eid": 3, "name": "OK", "control_type": "Button"}]
    assert out["ribbon_tabs"] == ["Home"]
    assert out["knowledge"].startswith("[pivot_basic]")
    assert out["steps"][0]["value"] == "[path]" and "rect" not in out["steps"][0]
    assert out["steps"][1]["element_name"] in ("[email]", None)
    assert out["steps"][2]["element_name"] is None
    assert len(out["steps"]) == 3
    assert out["step"] == {"id": 1, "intent": "invoke", "target": {"names": ["OK"]}}
    assert "z@z.zz" not in out["previous_output"] and out["errors"] == "bad"
    for k in ("screenshot", "cell_values", "title"):
        assert k not in out


def test_wrong_types_are_dropped():
    out = sanitize({"env": "x", "elements": "x", "ribbon_tabs": "x", "knowledge": 1, "steps": "x", "step": []})
    assert out == {}
