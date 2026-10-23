"""LLM client: provider chain + per-tutorial call budget (ADR-5) + pydantic validation with repair.

A repair attempt is a real call and counts against the same budget.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable, TypeVar

import structlog
from pydantic import BaseModel, ValidationError

from .config import LLMConfig
from .providers.base import LLMError, LLMProvider, LLMTimeout, ProviderUnavailable, QuotaExceeded
from .sanitizer import sanitize

log = structlog.get_logger()
M = TypeVar("M", bound=BaseModel)
MIN_CALL_SECONDS = 4.0  # below this a CPU model cannot answer; skip the call


class BudgetExceeded(LLMError):
    pass


@dataclass
class CallRecord:
    role: str
    provider: str
    model: str
    seconds: float
    ok: bool
    error: str | None = None


@dataclass
class Budget:
    max_calls: int
    used: int = 0
    log: list[CallRecord] = field(default_factory=list)
    deadline: float | None = None  # time.monotonic() by which the whole tutorial must be done

    def seconds_left(self, reserve: float = 0.0) -> float:
        return float("inf") if self.deadline is None else self.deadline - time.monotonic() - reserve

    @property
    def remaining(self) -> int:
        return self.max_calls - self.used


def build_providers(cfg: LLMConfig) -> list[LLMProvider]:
    from .providers.ollama import OllamaProvider
    from .providers.openai_compat import OpenAICompatProvider
    out: list[LLMProvider] = []
    for name in [cfg.provider] + [f for f in cfg.fallback if f != cfg.provider]:
        conf = cfg.providers.get(name)
        if conf is None or not conf.enabled:
            continue
        out.append(OllamaProvider(conf) if conf.is_local else OpenAICompatProvider(conf))
    return out


class LLMClient:
    def __init__(self, cfg: LLMConfig, providers: list[LLMProvider] | None = None,
                 budget: Budget | None = None):
        self.cfg = cfg
        self.providers = providers if providers is not None else build_providers(cfg)
        self.budget = budget or Budget(cfg.max_calls)

    def _model_for(self, provider: LLMProvider, role: str) -> str:
        if provider.is_local:
            return {"planner": self.cfg.planner_model, "writer": self.cfg.writer_model,
                    "grounder": self.cfg.grounder_model}[role]
        conf = self.cfg.providers[provider.name]
        if not conf.models:
            raise ProviderUnavailable(f"{provider.name}: no model configured")
        return conf.models[0]

    def _call(self, role: str, system: str, payload: dict, schema: dict, reserve: float = 0.0) -> str:
        if self.budget.remaining <= 0:
            raise BudgetExceeded(f"LLM budget of {self.budget.max_calls} calls used up")
        left = self.budget.seconds_left(reserve)
        if left < MIN_CALL_SECONDS:
            raise LLMTimeout(f"{role}: only {max(left, 0):.0f} s left in the tutorial time budget")
        timeout = None if left == float("inf") else left
        errors = []
        for p in self.providers:
            body = payload if p.is_local else sanitize(payload)  # §7.3: cloud only sees sanitized data
            try:
                model = self._model_for(p, role)
            except ProviderUnavailable as e:
                errors.append(str(e))
                continue
            t0 = time.monotonic()
            self.budget.used += 1
            try:
                text = p.complete_json(model, system, json.dumps(body, ensure_ascii=False), schema, timeout=timeout)
                self.budget.log.append(CallRecord(role, p.name, model, time.monotonic() - t0, True))
                return text
            except (QuotaExceeded, ProviderUnavailable) as e:
                self.budget.used -= 1  # nothing was generated; try the next provider for free
                self.budget.log.append(CallRecord(role, p.name, model, time.monotonic() - t0, False, str(e)))
                errors.append(str(e))
                log.warning("llm.provider_failed", provider=p.name, error=str(e))
        raise ProviderUnavailable("; ".join(errors) or "no LLM provider enabled")

    def complete(self, role: str, system: str, payload: dict, out: type[M],
                 max_repairs: int = 2, check: Callable[[M], list[str]] | None = None, reserve: float = 0.0) -> M:
        """Call, validate with pydantic (+ optional semantic check), repair up to max_repairs times."""
        schema = out.model_json_schema()
        text = self._call(role, system, payload, schema, reserve)
        for attempt in range(max_repairs + 1):
            try:
                obj = out.model_validate_json(text)
                problems = check(obj) if check else []
                if not problems:
                    return obj
                err = "; ".join(problems)
            except ValidationError as e:
                err = str(e)[:800]
            if attempt == max_repairs or self.budget.remaining <= 0:
                raise LLMError(f"{role}: invalid output after {attempt + 1} tries: {err}")
            repair = dict(payload)
            repair["previous_output"] = text[:4000]
            repair["errors"] = err
            text = self._call(role, system + " Sửa lại JSON trước đó cho đúng; chỉ trả JSON.", repair, schema, reserve)
        raise LLMError("unreachable")
