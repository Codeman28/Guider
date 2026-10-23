import io
import json
import threading
import time

import pytest

from kem_engine.grounding.llm_grounder import LLMDisambiguator
from kem_engine.llm.client import Budget, LLMClient
from kem_engine.llm.config import LLMConfig
from kem_engine.llm.providers.base import ProviderUnavailable
from kem_engine.models import EnvProfile, Locator, Plan, Trace, TraceStep, Tutorial
from kem_engine.orchestrator.service import text_matches_trace
from kem_engine.recipes.store import Store, plan_with_locators, recipe_key
from kem_engine.rpc import export
from kem_engine.rpc.server import Server
from kem_engine.verify.checks import COM_PROPS, com_check, compare
from kem_engine.writer import llm_writer, template

ENV = EnvProfile(app="excel", office_version="16.0", office_build="20326", ui_lang="en-US", ui_lcid=1033,
                 dpi=120, scale_pct=125, screen=(1920, 1080))
PLAN = Plan.model_validate_json(open("plans/pivot_basic.json", encoding="utf-8").read())


class Fake:
    is_local = True
    name = "ollama"
    supports_json_schema = True

    def __init__(self, replies):
        self.replies = list(replies)

    def complete_json(self, *a, **k):
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def client(replies, budget=3):
    return LLMClient(LLMConfig.load(), [Fake(replies)], Budget(budget))


def trace(verified=True):
    steps = [TraceStep(id=1, plan_step_id=1, intent="select_ribbon_tab", element_name="Insert", control_type="TabItem",
                       access_key="Alt, N", verified=verified, image="step_01.png",
                       locator=Locator(automation_id="TabInsert", control_type="TabItem", name="Insert")),
             TraceStep(id=2, plan_step_id=2, intent="invoke", element_name="PivotTable", control_type="Button",
                       verified=True, image="step_02.png",
                       locator=Locator(control_type="Button", name="PivotTable", within="Tables")),
             TraceStep(id=3, plan_step_id=3, intent="invoke", element_name="OK", control_type="Button",
                       verified=True, image="step_03.png", locator=Locator(control_type="Button", name="OK"))]
    return Trace(session_id="s", task_canonical="pivot_basic", env=ENV, steps=steps)


# ---- writer ----------------------------------------------------------------------------------

def wout(**over):
    d = {"title": "Tạo PivotTable", "intro": "Mở đầu.", "outro": "Hết.", "steps": [
        {"id": 1, "heading": "Mở thẻ **Insert**", "body": "Bấm **Chèn**.", "tip": "Phím tắt Alt, N"},
        {"id": 2, "heading": "Bước 2: Nhấn **PivotTable**", "body": "Nhấn **PivotTable**.", "tip": "Ctrl+P"},
        {"id": 3, "heading": "Bước 3: **OK**", "body": "Nhấn **OK**.", "tip": None}]}
    d.update(over)
    return json.dumps(d, ensure_ascii=False)


def test_llm_writer_fixes_labels_and_tips():
    tut, src = llm_writer.write(trace(), "T", "id", "ok", client([wout()]))
    assert src == "llm" and tut.title == "T"  # title and headings stay deterministic
    assert tut.steps[0].heading == "Bước 1: Mở thẻ **Insert**"
    assert tut.steps[0].body == "Bấm **Insert**."  # invented label replaced by the UIA name
    assert tut.steps[0].tip == "Phím tắt Alt, N"
    assert tut.steps[1].tip is None  # invented shortcut dropped
    assert tut.outro == "Hết."
    assert template.validate_labels(tut, trace()) == []
    assert tut.steps[0].image == "step_01.png"


def test_llm_writer_quotes_become_bold_or_template_body():
    out = wout(steps=[{"id": 1, "heading": "x", "body": "Chọn tab 'Insert' nhé."},
                      {"id": 2, "heading": "x", "body": "Nhấn nút để tiếp tục."},
                      {"id": 3, "heading": "x", "body": "Nhấn “OK”."}])
    tut, _ = llm_writer.write(trace(), "T", "id", "ok", client([out]))
    assert tut.steps[0].body == "Chọn tab **Insert** nhé."
    assert tut.steps[1].body == "Nhấn **PivotTable**."  # no label → template body
    assert tut.steps[2].body == "Nhấn **OK**."


def test_llm_writer_falls_back():
    t = trace()
    assert llm_writer.write(t, "T", "id", "ok", None)[1] == "template"
    assert llm_writer.write(t, "T", "id", "ok", client([], budget=0))[1] == "template"
    assert llm_writer.write(t, "T", "id", "ok", client([ProviderUnavailable("down")]))[1] == "template"
    bad_ids = wout(steps=[{"id": 9, "heading": "x", "body": "y"}])
    assert llm_writer.write(t, "T", "id", "ok", client([bad_ids, bad_ids]))[1] == "template"


def test_writer_problems():
    out = llm_writer.WOut.model_validate_json(wout())
    probs = llm_writer.problems(out, trace())
    assert any("Chèn" in p for p in probs)


# ---- grounder fallback -------------------------------------------------------------------------

def test_disambiguator(make_el):
    from kem_engine.models import Step, Target
    step = Step(id=1, intent="invoke", target=Target(names=["Recommended Charts"], control_type="Button"))
    cands = [make_el(1, "Recommended Charts", "Button"), make_el(2, "Recommended Charts", "Button")]
    d = LLMDisambiguator(client(['{"eid": 2}']))
    assert d(step, cands).eid == 2
    assert d(step, cands) is None  # one use per tutorial
    assert LLMDisambiguator(client(['{"eid": 7}']))(step, cands) is None
    assert LLMDisambiguator(client([ProviderUnavailable("x")]))(step, cands) is None
    assert LLMDisambiguator(client([]))(step, cands[:1]) is None


# ---- recipes ---------------------------------------------------------------------------------

def test_recipe_roundtrip(tmp_path):
    st = Store(tmp_path / "k.db")
    assert not st.save_recipe(PLAN, trace(verified=False), "v")
    tut = template.write(trace(), "T", "id", "ok")
    assert st.save_recipe(PLAN, trace(), "v", tut)
    plan, text = st.get_recipe("excel", "pivot_basic", ENV)
    assert plan.steps[0].target.automation_id == "TabInsert" and plan.steps[1].target.names[0] == "PivotTable"
    assert text.steps[0].heading == tut.steps[0].heading
    assert st.get_recipe("excel", "pivot_basic", ENV.model_copy(update={"office_build": "1"})) is None
    st.remember_question("tao pivot", "pivot_basic")
    assert st.task_for_question("tao pivot") == "pivot_basic" and st.task_for_question("x") is None
    st.save_env(ENV, ["Home"])
    assert st.get_env("excel") == (ENV, ["Home"]) and st.get_env("word") is None
    st.add_tutorial(tut, tmp_path, 2, "card")
    assert st.list_tutorials()[0]["llm_calls"] == 2 and st.tutorial_path("id") == tmp_path
    assert st.tutorial_path("nope") is None


def test_recipe_key_changes_with_env():
    assert recipe_key("excel", "t", ENV) != recipe_key("excel", "t", ENV.model_copy(update={"ui_lang": "vi-VN"}))


def test_plan_with_locators_skips_missing():
    t = trace()
    t.steps = t.steps[:1]
    p = plan_with_locators(PLAN, t)
    assert p.steps[0].target.names[0] == "Insert" and p.steps[1] == PLAN.steps[1]


def test_text_matches_trace():
    tut = template.write(trace(), "T", "id", "ok")
    assert text_matches_trace(tut, trace())
    t2 = trace()
    t2.steps[1].element_name = "Recommended PivotTables"
    assert not text_matches_trace(tut, t2)
    t2.steps = t2.steps[:2]
    assert not text_matches_trace(tut, t2)


# ---- COM check allowlist ----------------------------------------------------------------------

class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_compare_ops():
    assert compare(True, "true", None) and compare(-1, "true", None) and not compare(0, "true", None)
    assert compare(False, "false", None) and compare(0, "false", None)
    assert compare("0.0%", "contains", "%") and compare(3, "gte", 1) and not compare(None, "gte", 1)
    assert compare(2, "eq", 2)


def test_com_check_uses_allowlist_only():
    ws = Obj(AutoFilterMode=True, Range=lambda ref: Obj(Font=Obj(Bold=True), Value=((3,), (2,), (1,))))
    doc = Obj(Worksheets=lambda i: ws, Windows=lambda i: Obj(FreezePanes=True))
    assert com_check(doc, "sheet.autofilter", None, "true", None)
    assert com_check(doc, "range.font.bold", "A1", "true", None)
    assert com_check(doc, "range.sorted_desc", "D2:D4", "true", None)
    assert com_check(doc, "window.freeze_panes", None, "true", None)
    with pytest.raises(KeyError):
        com_check(doc, "__import__('os')", None, "eq", 1)
    assert all("." in k for k in COM_PROPS)


# ---- export ----------------------------------------------------------------------------------

def _tutorial_dir(tmp_path):
    from PIL import Image
    d = tmp_path / "t1"
    d.mkdir()
    Image.new("RGB", (4, 4), (255, 0, 0)).save(d / "step_01.png")
    tut = template.write(trace(), "Tạo <PivotTable>", "t1", "ok")
    tut.steps = tut.steps[:1]
    (d / "tutorial.json").write_text(tut.model_dump_json(), encoding="utf-8")
    (d / "manifest.json").write_text(json.dumps({"files": ["tutorial.json"]}), encoding="utf-8")
    return d


def test_export_md_html(tmp_path):
    d = _tutorial_dir(tmp_path)
    md = export.export(d, "md").read_text(encoding="utf-8")
    assert "# Tạo <PivotTable>" in md and "![" in md and "> Phím tắt" in md
    h = export.export(d, "html").read_text(encoding="utf-8")
    assert "data:image/png;base64," in h and "&lt;PivotTable&gt;" in h and "<strong>Insert</strong>" in h
    files = json.loads((d / "manifest.json").read_text(encoding="utf-8"))["files"]
    assert "tutorial.md" in files and "tutorial.html" in files
    with pytest.raises(ValueError):
        export.export(d, "pdf")


# ---- JSON-RPC server -------------------------------------------------------------------------

class FakeService:
    def __init__(self, store, done=None):
        self.store = store
        self.done = done

    def create(self, query, app_hint, progress, cancel_event):
        from kem_engine.orchestrator.service import CreateResult
        progress({"state": "PLAN", "message": "x"})
        if self.done:
            self.done.wait(2)
        return CreateResult("text", answer=f"echo {query}")


def rpc(tmp_path, done=None):
    lines = []
    store = Store(tmp_path / "k.db")
    s = Server(lambda: FakeService(store, done), tmp_path / "tut", write=lines.append,
               settings_path=tmp_path / "settings.json")
    return s, lines, store


def msgs(lines):
    return [json.loads(x) for x in lines]


def test_rpc_errors(tmp_path):
    s, lines, _ = rpc(tmp_path)
    s.handle_line("{not json")
    s.handle_line('{"jsonrpc": "1.0", "id": 1, "method": "x"}')
    s.handle_line('[1]')
    s.handle_line('{"jsonrpc": "2.0", "id": 2, "method": "nope"}')
    s.handle_line('{"jsonrpc": "2.0", "id": 3, "method": "tutorial.create", "params": []}')
    s.handle_line('{"jsonrpc": "2.0", "id": 4, "method": "tutorial.create", "params": {"query": " "}}')
    s.handle_line('{"jsonrpc": "2.0", "id": 5, "method": "tutorial.get", "params": {"tutorial_id": "x"}}')
    s.handle_line('{"jsonrpc": "2.0", "id": 6, "method": "settings.set", "params": {"evil": 1}}')
    codes = [m["error"]["code"] for m in msgs(lines)]
    assert codes == [-32700, -32600, -32600, -32601, -32602, -32602, -32602, -32602]


def test_rpc_create_progress_done_and_busy(tmp_path):
    done = threading.Event()
    s, lines, _ = rpc(tmp_path, done)
    s.handle_line('{"jsonrpc": "2.0", "id": 1, "method": "tutorial.create", "params": {"query": "pivot"}}')
    s.handle_line('{"jsonrpc": "2.0", "id": 2, "method": "tutorial.create", "params": {"query": "again"}}')
    sid = msgs(lines)[0]["result"]["session_id"]
    s.handle_line(json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tutorial.cancel", "params": {"session_id": sid}}))
    done.set()
    for _ in range(50):
        if any(m.get("method") == "tutorial.done" for m in msgs(lines)):
            break
        time.sleep(0.05)
    m = msgs(lines)
    assert any(x.get("error", {}).get("code") == -32001 for x in m)
    assert any(x.get("id") == 3 and x["result"]["ok"] for x in m)
    assert any(x.get("method") == "tutorial.progress" and x["params"]["session_id"] == sid for x in m)
    final = next(x for x in m if x.get("method") == "tutorial.done")
    assert final["params"]["answer"] == "echo pivot"


def test_rpc_list_get_export_settings(tmp_path):
    s, lines, store = rpc(tmp_path)
    d = _tutorial_dir(tmp_path)
    store.add_tutorial(Tutorial.model_validate_json((d / "tutorial.json").read_text(encoding="utf-8")), d, 1, "card")
    s.serve(io.StringIO(
        '{"jsonrpc": "2.0", "id": 1, "method": "tutorial.list"}\n\n'
        '{"jsonrpc": "2.0", "id": 2, "method": "tutorial.get", "params": {"tutorial_id": "t1"}}\n'
        '{"jsonrpc": "2.0", "id": 3, "method": "tutorial.export", "params": {"tutorial_id": "t1", "format": "html"}}\n'
        '{"jsonrpc": "2.0", "id": 4, "method": "tutorial.export", "params": {"tutorial_id": "t1", "format": "pdf"}}\n'
        '{"jsonrpc": "2.0", "id": 5, "method": "settings.get"}\n'
        '{"jsonrpc": "2.0", "id": 6, "method": "settings.set", "params": {"accent": "#123456"}}\n'
        '{"jsonrpc": "2.0", "id": 7, "method": "settings.get"}\n'
        '{"jsonrpc": "2.0", "method": "tutorial.list"}\n'
        '{"jsonrpc": "2.0", "id": 8, "method": "tutorial.cancel", "params": {"session_id": "none"}}\n'))
    m = {x["id"]: x for x in msgs(lines)}
    assert m[1]["result"][0]["tutorial_id"] == "t1"
    assert m[2]["result"]["dir"] == str(d)
    assert m[3]["result"]["path"].endswith("tutorial.html")
    assert m[4]["error"]["code"] == -32602
    assert m[5]["result"] == {} and m[7]["result"] == {"accent": "#123456"}
    assert m[8]["result"] == {"ok": False}
    assert len(m) == 8  # the notification without id got no reply


def test_rpc_get_includes_trace_and_shutdown_cancels(tmp_path):
    s, lines, store = rpc(tmp_path)
    d = _tutorial_dir(tmp_path)
    (d / "trace.json").write_text(trace().model_dump_json(), encoding="utf-8")
    store.add_tutorial(Tutorial.model_validate_json((d / "tutorial.json").read_text(encoding="utf-8")), d, 1, "card")
    s.handle_line('{"jsonrpc": "2.0", "id": 1, "method": "tutorial.get", "params": {"tutorial_id": "t1"}}')
    got = msgs(lines)[0]["result"]["trace"]
    assert got["steps"][0]["element_name"] == "Insert" and "rect" not in got["steps"][0]
    ev = threading.Event()
    s.active["x"] = ev
    s.shutdown(timeout=0.1)
    assert ev.is_set()


def test_check_model_reports_unreachable(monkeypatch):
    from kem_engine.rpc import server as srv
    monkeypatch.setenv("KEM_LLM_CONFIG", str(_cfg_unreachable()))
    r = srv.check_model()
    assert r["ok"] is False and "error" in r


def _cfg_unreachable():
    import tempfile
    p = tempfile.mktemp(suffix=".toml")
    open(p, "w", encoding="utf-8").write('[default]\nprovider="ollama"\nplanner_model="m"\nwriter_model="m"\n'
                                         '[ollama]\nbase_url="http://127.0.0.1:9"\n')
    return p


def test_llm_writer_keeps_undemonstrated_sentence_and_times_out_to_template():
    t = trace()
    t.steps[2].verified = False
    out = wout(steps=[{"id": 1, "heading": "x", "body": "Bấm **Insert**."},
                      {"id": 2, "heading": "x", "body": "Nhấn **PivotTable**."},
                      {"id": 3, "heading": "x", "body": "Nhấn **OK** là xong."}])
    tut, src = llm_writer.write(t, "T", "id", "partial", client([out]))
    assert src == "llm" and tut.steps[2].body.startswith("Bước này Guider chưa làm mẫu được trên máy bạn")
    from kem_engine.llm.providers.base import LLMTimeout
    assert llm_writer.write(trace(), "T", "id", "ok", client([LLMTimeout("slow")]))[1] == "template"
