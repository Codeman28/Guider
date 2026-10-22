import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from kem_engine.intent.knowledge import KnowledgePack, fold
from kem_engine.intent.router import route
from kem_engine.llm.client import Budget, BudgetExceeded, LLMClient
from kem_engine.llm.config import LLMConfig
from kem_engine.llm.providers.base import LLMError, ProviderUnavailable, QuotaExceeded
from kem_engine.models import EnvProfile
from kem_engine.planner.planner import LLMPlan, Planner, is_troubleshooting, semantic_problems, to_plan
from kem_engine.safety.guard import Blocklist

CFG_TOML = """
[default]
provider = "ollama"
planner_model = "m-plan"
writer_model = "m-write"
grounder_model = "m-ground"
fallback = ["openrouter", "gemini"]
[ollama]
base_url = "http://127.0.0.1:11434"
[openrouter]
enabled = true
base_url = "https://example.invalid/api/v1"
api_key_env = "KEM_TEST_KEY"
models = ["x:free"]
[gemini]
enabled = false
base_url = "https://example.invalid/"
model = ""
[budget]
max_llm_calls_per_tutorial = 3
"""

ENV = EnvProfile(app="excel", office_version="16.0", office_build="20326", ui_lang="en-US", ui_lcid=1033,
                 dpi=120, scale_pct=125, screen=(1920, 1080))


@pytest.fixture
def cfg(tmp_path):
    p = tmp_path / "llm.toml"
    p.write_text(CFG_TOML, encoding="utf-8")
    return LLMConfig.load(p)


class Fake:
    def __init__(self, name, replies, local=True):
        self.name, self.is_local, self.supports_json_schema = name, local, True
        self.replies = list(replies)
        self.seen = []

    def complete_json(self, model, system, user, schema, temperature=0.2, max_tokens=2000):
        self.seen.append((model, json.loads(user)))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class Out(BaseModel):
    x: int


def test_config_loads_providers(cfg, monkeypatch):
    assert cfg.provider == "ollama" and cfg.max_calls == 3 and cfg.fallback == ["openrouter", "gemini"]
    assert cfg.providers["ollama"].is_local and not cfg.providers["openrouter"].is_local
    assert cfg.providers["gemini"].models == []
    monkeypatch.setenv("KEM_TEST_KEY", "k")
    assert cfg.providers["openrouter"].api_key() == "k"
    from kem_engine.llm.client import build_providers
    assert [p.name for p in build_providers(cfg)] == ["ollama", "openrouter"]


def test_shipped_config_loads():
    c = LLMConfig.load()
    assert c.provider == "ollama" and c.max_calls == 3


def test_complete_validates_and_counts(cfg):
    f = Fake("ollama", ['{"x": 1}'])
    c = LLMClient(cfg, [f])
    assert c.complete("planner", "s", {"question": "q"}, Out).x == 1
    assert c.budget.used == 1 and f.seen[0][0] == "m-plan"


def test_repair_counts_against_budget(cfg):
    f = Fake("ollama", ['{"x": "no"}', '{"x": 2}'])
    c = LLMClient(cfg, [f])
    assert c.complete("writer", "s", {"question": "q"}, Out).x == 2
    assert c.budget.used == 2 and "errors" in f.seen[1][1] and f.seen[1][0] == "m-write"


def test_repair_gives_up(cfg):
    c = LLMClient(cfg, [Fake("ollama", ['{"x": "a"}', '{"x": "b"}'])])
    with pytest.raises(LLMError, match="invalid output"):
        c.complete("planner", "s", {}, Out, max_repairs=1)


def test_semantic_check_triggers_repair(cfg):
    c = LLMClient(cfg, [Fake("ollama", ['{"x": 1}', '{"x": 5}'])])
    out = c.complete("planner", "s", {}, Out, check=lambda o: [] if o.x > 3 else ["x too small"])
    assert out.x == 5


def test_budget_exceeded(cfg):
    c = LLMClient(cfg, [Fake("ollama", ['{"x": 1}'])], Budget(0))
    with pytest.raises(BudgetExceeded):
        c.complete("planner", "s", {}, Out)


def test_fallback_to_cloud_is_sanitized_and_free_on_quota(cfg):
    local = Fake("ollama", [ProviderUnavailable("down")])
    cloud = Fake("openrouter", [QuotaExceeded("429"), ], local=False)
    cloud2 = Fake("openrouter", ['{"x": 3}'], local=False)
    c = LLMClient(cfg, [local, cloud, cloud2])
    out = c.complete("planner", "s", {"question": "x@y.com", "screenshot": "AAA"}, Out)
    assert out.x == 3 and c.budget.used == 1
    sent = cloud2.seen[0][1]
    assert sent == {"question": "[email]"} and cloud2.seen[0][0] == "x:free"


def test_all_providers_down(cfg):
    c = LLMClient(cfg, [Fake("ollama", [ProviderUnavailable("down")])])
    with pytest.raises(ProviderUnavailable, match="down"):
        c.complete("planner", "s", {}, Out)
    assert c.budget.used == 0


def test_cloud_without_model_is_skipped(cfg):
    cfg.providers["openrouter"].models = []
    c = LLMClient(cfg, [Fake("openrouter", [], local=False)])
    with pytest.raises(ProviderUnavailable, match="no model"):
        c.complete("planner", "s", {}, Out)


# ---- router / knowledge -----------------------------------------------------------------------

@pytest.mark.parametrize("q,in_scope", [
    ("Cách tạo PivotTable trong Excel", True),
    ("tại sao biểu đồ bị lệch", True),          # "tại" must not read as "tải"
    ("cái nút in đậm ở đâu", True),             # "cái" must not read as "cài"
    ("tải Excel miễn phí ở đâu", False),
    ("cài đặt Office", False),
    ("gửi file excel qua email cho sếp", False),
    ("how to send email", False),
    ("chia sẻ file lên OneDrive", False),
    ("đăng nhập tài khoản Microsoft", False),
    ("chạy macro VBA", False),
    ("hỏi Copilot", False),
])
def test_router_scope(q, in_scope):
    assert route(q).in_scope is in_scope


def test_router_apps():
    assert route("tạo slide PowerPoint").in_scope is False
    assert route("soạn văn bản Word").app == "word"
    r = route("in đậm chữ")
    assert r.in_scope and r.app == "excel" and r.unsure_app
    assert route("x", app_hint="excel").app == "excel"


def test_fold():
    assert fold("Biểu đồ  CỘT!") == "bieu do cot"


def test_card_match_with_and_without_diacritics():
    k = KnowledgePack()
    assert k.match("làm sao cố định dòng đầu tiên")[0][1].id == "freeze_top_row"
    assert k.match("bieu do tron")[0][1].id == "chart_pie"
    assert k.match("tô màu nền ô")[0][1].id == "fill_color"
    assert k.version.startswith("1-")
    assert "pivot_basic" in k.by_id["pivot_basic"].summary()


# ---- planner ---------------------------------------------------------------------------------

PLAN_OK = {"in_scope": True, "title": "Đếm", "task_canonical": "count_blank", "fixture_id": "sales_table_basic",
           "select_range": "A1:D21",
           "steps": [{"intent": "select_ribbon_tab", "target": {"names": ["Formulas"], "control_type": "TabItem"}},
                     {"intent": "expand", "target": {"names": ["More Functions"], "control_type": "MenuItem",
                                                     "within_group": "Function Library"}},
                     {"intent": "set_value", "value": "3",
                      "target": {"names": ["Name Box"], "control_type": "Edit"}}]}


def test_card_used_directly_without_llm():
    r = Planner(KnowledgePack(), None).plan("Cách tạo PivotTable trong Excel", ENV)
    assert r.source == "card" and r.plan.task_canonical == "pivot_basic"


def test_troubleshooting_goes_to_llm(cfg):
    assert is_troubleshooting("Tại sao biểu đồ cột bị lệch?")
    r = Planner(KnowledgePack(), None).plan("tại sao biểu đồ cột bị lệch", ENV)
    assert r.plan is None and r.source == "none"


def test_llm_plan_path(cfg):
    f = Fake("ollama", [json.dumps(PLAN_OK)])
    r = Planner(KnowledgePack(), LLMClient(cfg, [f])).plan("đếm ô trống", ENV, ["Home", "Formulas"])
    assert r.source == "llm" and r.plan.steps[1].target.within.names == ["Function Library"]
    assert r.plan.preconditions[0].ref == "A1:D21"
    assert r.plan.steps[0].expected.type == "tab_selected" and r.plan.steps[1].expected.type == "expanded"
    sent = f.seen[0][1]
    assert sent["ribbon_tabs"] == ["Home", "Formulas"] and "knowledge" in sent


def test_llm_out_of_scope(cfg):
    f = Fake("ollama", [json.dumps({"in_scope": False, "reason": "cần mạng", "title": "x", "task_canonical": "x"})])
    r = Planner(KnowledgePack(), LLMClient(cfg, [f]), use_cards_directly=False).plan("Cách tạo PivotTable", None)
    assert not r.in_scope and r.reason == "cần mạng"


def test_semantic_problems():
    bl = Blocklist.load()
    p = LLMPlan.model_validate({**PLAN_OK, "fixture_id": "nope", "steps": [
        {"intent": "invoke", "target": {"names": ["Share"], "control_type": "Button"}},
        {"intent": "set_value", "target": {"names": [], "control_type": "Edit"}}]})
    probs = semantic_problems(p, bl)
    assert any("fixture_id" in x for x in probs) and any("bị cấm" in x for x in probs)
    assert any("rỗng" in x for x in probs) and any("cần value" in x for x in probs)
    assert semantic_problems(LLMPlan(in_scope=False, title="t", task_canonical="t"), bl)
    assert semantic_problems(LLMPlan(in_scope=True, title="t", task_canonical="t"), bl) == ["in_scope=true nhưng steps rỗng"]


def test_to_plan_defaults():
    p = to_plan(LLMPlan.model_validate({**PLAN_OK, "select_range": None, "fixture_id": None, "task_canonical": ""}))
    assert p.fixture_id == "sales_table_basic" and p.preconditions == [] and p.task_canonical == "llm_task"


def test_too_many_names_rejected_by_schema():
    with pytest.raises(Exception):
        LLMPlan.model_validate({**PLAN_OK, "steps": [{"intent": "invoke", "target": {
            "names": ["Home", "Insert", "Draw", "Page Layout", "Formulas"], "control_type": "TabItem"}}]})
