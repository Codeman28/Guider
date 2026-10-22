"""Grounder fallback (SPEC §6.5) — LLM call #3, only when fuzzy matching is ambiguous, at most once per
tutorial. The model picks one eid from a text-only candidate list or returns null."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from ..llm.client import LLMClient
from ..llm.providers.base import LLMError
from ..models import Step
from ..uia.element import Element

SYSTEM = ("Chọn đúng một eid trong danh sách 'candidates' phù hợp nhất với bước 'step', hoặc trả null nếu "
          "không có. Không suy diễn phần tử ngoài danh sách. Chỉ trả JSON.")


class Pick(BaseModel):
    eid: Optional[int] = None


class LLMDisambiguator:
    def __init__(self, llm: LLMClient, max_uses: int = 1):
        self.llm = llm
        self.left = max_uses

    def __call__(self, step: Step, candidates: list[Element]) -> Element | None:
        if self.left <= 0 or self.llm.budget.remaining <= 0 or len(candidates) < 2:
            return None
        self.left -= 1
        payload = {"step": {"id": step.id, "intent": step.intent, "target": step.target.model_dump()},
                   "candidates": [c.public() for c in candidates]}
        try:
            pick = self.llm.complete("grounder", SYSTEM, payload, Pick, max_repairs=0)
        except LLMError:
            return None
        return next((c for c in candidates if c.eid == pick.eid), None)
