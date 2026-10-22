"""Planner (SPEC §6.4) — LLM call #1, or 0 calls when a reviewed card / recipe matches.

The LLM never produces coordinates; its output is validated (pydantic + semantic checks) and repaired
within the per-tutorial budget.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..intent.knowledge import KnowledgePack
from ..llm.client import LLMClient
from ..models import EnvProfile, Plan, Precondition, Rect, Step, Target, Within
from ..safety.guard import Blocklist
from ..uia.element import Element

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"
CARD_DIRECT_THRESHOLD = 90.0
MAX_STEPS = 12
MAX_NAMES = 4
_ZERO = Rect(left=0, top=0, right=0, bottom=0)

SYSTEM = (
    "Bạn lập kế hoạch thao tác giao diện Microsoft 365 (Excel) trên Windows để làm mẫu trong một file trống. "
    "Chỉ dùng các intent trong schema. Không sinh tọa độ. Mỗi bước nhắm đúng MỘT nút; target.names là "
    "tên nút đó bằng tiếng Anh và tiếng Việt (tối đa 4 tên), không liệt kê các tab khác. "
    "Ưu tiên làm theo các thẻ tác vụ mẫu trong 'knowledge' nếu phù hợp. Vùng chọn ban đầu đặt trong "
    "preconditions (select_range), không phải trong steps. Nếu tác vụ cần tải/cài phần mềm, đăng nhập, "
    "gửi, chia sẻ hoặc không làm được trong một file trống: in_scope=false và reason ngắn bằng tiếng Việt. "
    "Chỉ trả JSON đúng schema."
)

LLMIntent = Literal["select_ribbon_tab", "invoke", "expand", "select_item", "toggle", "set_value"]


class LLMTarget(BaseModel):
    names: list[str] = Field(max_length=MAX_NAMES)
    control_type: str
    within_group: Optional[str] = None


class LLMStep(BaseModel):
    intent: LLMIntent
    target: LLMTarget
    value: Optional[str] = None


class LLMPlan(BaseModel):
    in_scope: bool
    reason: Optional[str] = None
    title: str
    task_canonical: str = Field(description="snake_case id ngắn của tác vụ")
    fixture_id: Optional[str] = None
    select_range: Optional[str] = Field(None, description="vùng chọn trước khi làm, ví dụ A1:D21")
    steps: list[LLMStep] = Field(default_factory=list, max_length=MAX_STEPS)


@dataclass
class PlanResult:
    plan: Plan | None
    source: Literal["card", "recipe", "llm", "none"]
    in_scope: bool = True
    reason: str | None = None
    card_score: float = 0.0


_TROUBLE = re.compile(r"\b(tại sao|vì sao|sao lại|bị lỗi|không được|không hiện|bị lệch|why|error|not working)\b")


def is_troubleshooting(question: str) -> bool:
    """'Why is my chart off?' is not 'how do I insert a chart' — let the Planner decide."""
    return bool(_TROUBLE.search(unicodedata.normalize("NFC", question).lower()))


def fixture_ids() -> list[str]:
    return sorted(p.stem for p in FIXTURES_DIR.glob("*.json"))


def semantic_problems(p: LLMPlan, blocklist: Blocklist) -> list[str]:
    if not p.in_scope:
        return [] if p.reason else ["in_scope=false cần reason"]
    probs = []
    if not p.steps:
        probs.append("in_scope=true nhưng steps rỗng")
    if p.fixture_id and p.fixture_id not in fixture_ids():
        probs.append(f"fixture_id phải thuộc {fixture_ids()}")
    for i, s in enumerate(p.steps, 1):
        if not s.target.names:
            probs.append(f"bước {i}: target.names rỗng")
        for n in s.target.names:
            el = Element(0, n, s.target.control_type, "", rect=_ZERO, root_hwnd=0)
            if blocklist.blocks(el):
                probs.append(f"bước {i}: '{n}' là nút bị cấm")
        if s.intent == "set_value" and not s.value:
            probs.append(f"bước {i}: set_value cần value")
    return probs


def to_plan(p: LLMPlan) -> Plan:
    steps = []
    for i, s in enumerate(p.steps, 1):
        within = Within(names=[s.target.within_group], control_type="Group") if s.target.within_group else None
        steps.append(Step(id=i, intent=s.intent, value=s.value,
                          target=Target(names=s.target.names, control_type=s.target.control_type, within=within),
                          expected={"type": "tab_selected"} if s.intent == "select_ribbon_tab" else
                          {"type": "expanded"} if s.intent == "expand" else {"type": "none"}))
    pre = [Precondition(type="select_range", ref=p.select_range)] if p.select_range else []
    return Plan(task_canonical=p.task_canonical or "llm_task", title=p.title,
                fixture_id=p.fixture_id or "sales_table_basic", preconditions=pre, steps=steps)


class Planner:
    def __init__(self, pack: KnowledgePack, llm: LLMClient | None, blocklist: Blocklist | None = None,
                 use_cards_directly: bool = True):
        self.pack = pack
        self.llm = llm
        self.blocklist = blocklist or Blocklist.load()
        self.use_cards_directly = use_cards_directly

    def plan(self, question: str, env: EnvProfile | None, ribbon_tabs: list[str] | None = None) -> PlanResult:
        matches = self.pack.match(question)
        best_score, best = matches[0] if matches else (0.0, None)
        if best and self.use_cards_directly and best_score >= CARD_DIRECT_THRESHOLD and not is_troubleshooting(question):
            return PlanResult(best.to_plan(), "card", card_score=best_score)
        if self.llm is None:
            return PlanResult(None, "none", reason="Không có model nào để lập kế hoạch cho câu hỏi này.")
        payload = {
            "question": question,
            "env": {"app": "excel", "ui_lang": env.ui_lang, "office_build": env.office_build} if env else {},
            "ribbon_tabs": ribbon_tabs or [],
            "knowledge": "\n".join(c.summary() for _, c in matches),
        }
        out = self.llm.complete("planner", SYSTEM, payload, LLMPlan,
                                check=lambda p: semantic_problems(p, self.blocklist))
        if not out.in_scope:
            return PlanResult(None, "llm", in_scope=False, reason=out.reason)
        return PlanResult(to_plan(out), "llm", card_score=best_score)
