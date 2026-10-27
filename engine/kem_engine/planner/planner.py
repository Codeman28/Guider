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
from ..llm.providers.base import LLMTimeout
from ..models import EnvProfile, Plan, Precondition, Rect, Step, Target, Within
from ..safety.guard import Blocklist
from ..uia.element import Element

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"
CARD_DIRECT_THRESHOLD = 95.0
MAX_STEPS = 12
MAX_NAMES = 4
_ZERO = Rect(left=0, top=0, right=0, bottom=0)

SYSTEM = (
    "Bạn lập kế hoạch thao tác giao diện Microsoft 365 (Excel, Word hoặc PowerPoint — xem env.app) trên Windows "
    "để làm mẫu trong một file trống. "
    "Chỉ dùng các intent trong schema. Không sinh tọa độ. Mỗi bước nhắm đúng MỘT nút; target.names là "
    "tên nút đó bằng tiếng Anh và tiếng Việt (tối đa 4 tên), không liệt kê các tab khác. "
    "Ưu tiên làm theo các thẻ tác vụ mẫu trong 'knowledge' nếu phù hợp. ƯU TIÊN BÀN PHÍM: trong Excel, việc tính "
    "toán thì gõ hàm (intent type_formula: target.names=[ô đích, ví dụ \"F2\"], control_type \"Cell\", value= công "
    "thức bắt đầu bằng =); việc có phím tắt chuẩn (Ctrl+B, Ctrl+I, Ctrl+U, Ctrl+E, Ctrl+Shift+L, Ctrl+T, Alt+=, "
    "Ctrl+M, Ctrl+Enter…) thì dùng intent key_combo (value = tổ hợp phím, target.names=[tổ hợp phím], control_type "
    "\"Keys\"); chỉ dùng nút trên ribbon khi không có cách gõ. Vùng chọn ban đầu đặt trong "
    "preconditions (select_range), không phải trong steps. Nếu tác vụ cần tải/cài phần mềm, đăng nhập, "
    "gửi, chia sẻ hoặc không làm được trong một file trống: in_scope=false và reason ngắn bằng tiếng Việt. "
    "Chỉ trả JSON đúng schema."
)

LLMIntent = Literal["select_ribbon_tab", "invoke", "expand", "select_item", "toggle", "set_value",
                    "type_formula", "key_combo"]


UIAType = Literal["TabItem", "Button", "SplitButton", "MenuItem", "ListItem", "CheckBox", "Edit", "ComboBox",
                  "RadioButton", "Cell", "Keys"]


class LLMTarget(BaseModel):
    names: list[str] = Field(max_length=MAX_NAMES)
    control_type: UIAType  # closed set → Ollama's grammar cannot emit 'button' or 'list_item'
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
    source: Literal["card", "card_llm", "card_fallback", "recipe", "llm", "none"]
    in_scope: bool = True
    reason: str | None = None
    card_score: float = 0.0


_TROUBLE = re.compile(r"\b(tại sao|vì sao|sao lại|bị lỗi|không được|không hiện|bị lệch|why|error|not working)\b")


def is_troubleshooting(question: str) -> bool:
    """'Why is my chart off?' is not 'how do I insert a chart' — let the Planner decide."""
    return bool(_TROUBLE.search(unicodedata.normalize("NFC", question).lower()))


CARD_RIVAL_THRESHOLD = 85.0


def card_is_clear(matches) -> bool:
    """Use a card directly only if it matches strongly and no other card comes close
    ("trộn ô và căn giữa" hits both merge_center and center_align → let the Planner choose)."""
    if not matches or matches[0][0] < CARD_DIRECT_THRESHOLD:
        return False
    if len(matches) < 2 or matches[1][0] < CARD_RIVAL_THRESHOLD:
        return True
    # keyboard-first (27/10/2026): a typed/shortcut card beats an equally good ribbon card without asking
    from ..intent.knowledge import is_keyboard
    return is_keyboard(matches[0][1]) and not is_keyboard(matches[1][1]) and matches[0][0] >= matches[1][0]


def slug(text: str) -> str:
    """'Create PivotTable' → 'create_pivottable' (the task id names folders and recipe keys)."""
    from ..intent.knowledge import fold
    return re.sub(r"[^a-z0-9]+", "_", fold(text or "")).strip("_")[:48]


CHOOSE_SYSTEM = (
    "Chọn thẻ tác vụ phù hợp nhất với câu hỏi của người dùng trong danh sách 'knowledge'. "
    "Trả card_id là id của thẻ đó, hoặc \"none\" nếu không thẻ nào làm đúng điều người dùng hỏi. Chỉ trả JSON."
)


def card_choice_model(ids: list[str]) -> type[BaseModel]:
    """Schema whose card_id is an enum of the candidate ids (+ 'none'): the model can only pick one."""
    from pydantic import create_model
    return create_model("CardChoice", card_id=(Literal[tuple(ids + ["none"])], ...))


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


DEFAULT_FIXTURE = {"excel": "sales_table_basic", "word": "word_report_basic", "powerpoint": "ppt_deck_basic"}


def to_plan(p: LLMPlan, app: str = "excel") -> Plan:
    steps = []
    for i, s in enumerate(p.steps, 1):
        if s.intent == "key_combo":
            steps.append(Step(id=i, intent="key_combo", value=s.value or (s.target.names[0] if s.target.names else ""),
                              expected={"type": "none"}))
            continue
        if s.intent == "type_formula":
            cell = s.target.names[0] if s.target.names else "A1"
            steps.append(Step(id=i, intent="type_formula", value=s.value or "", capture_result=True,
                              target=Target(names=[cell], control_type="Cell"),
                              expected={"type": "com_check", "prop": "cell.formula_ok", "ref": cell, "op": "true"}
                              if app == "excel" else {"type": "none"}))
            continue
        within = Within(names=[s.target.within_group], control_type="Group") if s.target.within_group else None
        steps.append(Step(id=i, intent=s.intent, value=s.value,
                          target=Target(names=s.target.names, control_type=s.target.control_type, within=within),
                          expected={"type": "tab_selected"} if s.intent == "select_ribbon_tab" else
                          {"type": "expanded"} if s.intent == "expand" else {"type": "none"}))
    pre = [Precondition(type="select_range", ref=p.select_range)] if p.select_range else []
    return Plan(task_canonical=slug(p.task_canonical) or "llm_task", title=p.title,
                fixture_id=p.fixture_id or DEFAULT_FIXTURE.get(app, "sales_table_basic"), preconditions=pre,
                steps=steps, app=app)


class Planner:
    def __init__(self, pack: KnowledgePack, llm: LLMClient | None, blocklist: Blocklist | None = None,
                 use_cards_directly: bool = True, reserve: float = 0.0, app: str = "excel"):
        self.app = app
        self.reserve = reserve  # seconds kept back for the demonstration (time budget)
        self.pack = pack
        self.llm = llm
        self.blocklist = blocklist or Blocklist.load()
        self.use_cards_directly = use_cards_directly

    def plan(self, question: str, env: EnvProfile | None, ribbon_tabs: list[str] | None = None) -> PlanResult:
        matches = self.pack.match(question)
        best_score, best = matches[0] if matches else (0.0, None)
        if best and self.use_cards_directly and card_is_clear(matches) and not is_troubleshooting(question):
            return PlanResult(best.to_plan(), "card", card_score=best_score)
        if self.llm is None:
            return PlanResult(None, "none", reason="Không có model nào để lập kế hoạch cho câu hỏi này.")

        # Several reviewed cards match: let the model choose among them (classification is within reach
        # of a 1.7B model; free-form planning is not — eval run 2).
        candidates = [c for s_, c in matches if s_ >= 85.0]
        if len(candidates) >= 2 and self.use_cards_directly:
            Choice = card_choice_model([c.id for c in candidates])
            try:
                pick = self.llm.complete("planner", CHOOSE_SYSTEM, {
                    "question": question, "knowledge": "\n".join(c.summary() for c in candidates)}, Choice,
                    max_repairs=0, reserve=self.reserve)
            except LLMTimeout:
                # out of time: the best-scoring reviewed card beats a late answer (< 2 min rule)
                return PlanResult(candidates[0].to_plan(), "card_fallback", card_score=best_score)
            if pick.card_id != "none":
                return PlanResult(self.pack.by_id[pick.card_id].to_plan(), "card_llm", card_score=best_score)

        payload = {
            "question": question,
            "env": {"app": self.app, "ui_lang": env.ui_lang, "office_build": env.office_build} if env else {"app": self.app},
            "ribbon_tabs": ribbon_tabs or [],
            "knowledge": "\n".join(c.summary() for _, c in matches),
        }
        out = self.llm.complete("planner", SYSTEM, payload, LLMPlan,
                                check=lambda p: semantic_problems(p, self.blocklist), reserve=self.reserve)
        if not out.in_scope:
            return PlanResult(None, "llm", in_scope=False, reason=out.reason)
        from .repair import repair
        fixed, _ = repair(to_plan(out, self.app))  # real ribbon names/tabs before anything is clicked
        if not fixed.steps:
            return PlanResult(None, "llm", in_scope=False,
                              reason="Guider chưa biết làm việc này. Bạn thử hỏi cách khác, hoặc dạy Guider ở khu Huấn luyện.")
        return PlanResult(fixed, "llm", card_score=best_score)
