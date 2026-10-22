"""Shared data contracts (SPEC §6.4, §6.10, §11). Every LLM/plan I/O goes through these."""
from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, Field

Intent = Literal["select_ribbon_tab", "invoke", "expand", "select_item", "toggle", "set_value",
                 "type_text", "key_combo", "select_range", "wait_for"]

# Expected-condition kinds the Verifier knows. COM checks are a closed set — never evaluated strings.
ExpectedType = Literal["tab_selected", "expanded", "dialog_opened", "dialog_closed",
                       "com_pivot_tables", "com_charts", "com_format_conditions", "com_check", "none"]


class Within(BaseModel):
    names: list[str]
    control_type: str


class Target(BaseModel):
    names: list[str]
    control_type: str  # "Button|SplitButton" = any of
    within: Optional[Within] = None
    automation_id: Optional[str] = None


class Expected(BaseModel):
    type: ExpectedType = "none"
    names: Optional[list[str]] = None
    min_count: int = 1
    # com_check: prop must be a key of verify.checks.COM_PROPS (closed allowlist, never evaluated)
    prop: Optional[str] = None
    ref: Optional[str] = None
    op: Literal["eq", "contains", "gte", "true", "false"] = "eq"
    value: Optional[Union[str, int, float, bool]] = None


class Step(BaseModel):
    id: int
    intent: Intent
    target: Optional[Target] = None
    value: Optional[str] = None
    expected: Expected = Field(default_factory=Expected)
    capture_result: bool = False  # also screenshot after the action (e.g. a dialog opened)


class Precondition(BaseModel):
    type: Literal["select_range"]
    ref: str


class Plan(BaseModel):
    task_canonical: str
    app: Literal["excel"] = "excel"
    title: str
    fixture_id: Optional[str] = None
    preconditions: list[Precondition] = []
    steps: list[Step]
    success_check: Optional[Expected] = None  # task-level COM assertion (cards, eval)


class EnvProfile(BaseModel):
    app: str
    office_version: str
    office_build: str  # normalized major build, e.g. "20326"
    ui_lang: str  # BCP-47, e.g. "en-US"
    ui_lcid: int
    dpi: int
    scale_pct: int
    screen: tuple[int, int]


class Rect(BaseModel):
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def contains(self, other: "Rect", slack: int = 2) -> bool:
        return (other.left >= self.left - slack and other.top >= self.top - slack
                and other.right <= self.right + slack and other.bottom <= self.bottom + slack)


class Locator(BaseModel):
    automation_id: Optional[str] = None
    control_type: str
    name: str
    within: Optional[str] = None


class TraceStep(BaseModel):
    id: int
    plan_step_id: Optional[int]  # None for steps inserted by the Grounder's repair rules
    intent: Intent
    element_name: Optional[str] = None
    control_type: Optional[str] = None
    access_key: Optional[str] = None
    value: Optional[str] = None
    locator: Optional[Locator] = None
    rect: Optional[Rect] = None
    image: Optional[str] = None
    result_image: Optional[str] = None
    inserted_reason: Optional[str] = None
    grounding_score: Optional[float] = None
    ambiguous: bool = False
    verified: bool = False
    attempts: int = 0
    error: Optional[str] = None


class Trace(BaseModel):
    session_id: str
    task_canonical: str
    env: EnvProfile
    steps: list[TraceStep] = []
    state: str = "IDLE"
    llm_calls: int = 0


class TutorialStep(BaseModel):
    id: int
    heading: str
    body: str
    tip: Optional[str] = None
    image: Optional[str] = None
    result_image: Optional[str] = None
    demonstrated: bool = True


class Tutorial(BaseModel):
    tutorial_id: str
    title: str
    intro: str
    steps: list[TutorialStep]
    outro: str
    env_label: str
    status: Literal["ok", "partial", "failed", "cancelled"]
