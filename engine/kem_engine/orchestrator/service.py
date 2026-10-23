"""Question → tutorial (SPEC §4.2): route → recipe | card | Planner → Session → Writer → recipe store.

LLM budget per tutorial (ADR-5): Planner ≤1 (+repairs), Writer 1, Grounder ≤1, total ≤ max_calls.
Recipe replay: 0 calls (plan from cache, text reused when the grounded steps are identical).
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import structlog

from ..grounding.llm_grounder import LLMDisambiguator
from ..intent.knowledge import KnowledgePack, fold
from ..intent.router import route
from ..llm.client import LLMClient
from ..llm.config import LLMConfig
from ..llm.providers.base import LLMError
from ..models import Expected, Plan, Trace, Tutorial
from ..planner.planner import Planner, card_is_clear
from ..recipes.store import Store
from ..writer import llm_writer, template
from .session import Session

log = structlog.get_logger()


@dataclass
class CreateResult:
    kind: str  # "tutorial" | "text"
    answer: str | None = None
    tutorial_id: str | None = None
    status: str | None = None
    path: str | None = None
    llm_calls: int = 0
    plan_source: str | None = None
    writer_source: str | None = None
    seconds: float = 0.0
    llm_log: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def text_matches_trace(text: Tutorial, trace: Trace) -> bool:
    """Stored tutorial text can be reused if every step's bold labels name the same element."""
    if len(text.steps) != len(trace.steps):
        return False
    for st, ts in zip(text.steps, trace.steps):
        labels = set(template.bold_labels(st.heading) + template.bold_labels(st.body))
        if labels - {template.clean(ts.element_name or "")}:
            return False
    return True


class TutorialService:
    def __init__(self, out_root: Path, store: Store | None = None, cfg: LLMConfig | None = None,
                 llm_factory: Callable[[LLMConfig], LLMClient | None] | None = None,
                 window_logical: tuple[int, int] = (1280, 800), use_cards_directly: bool = True):
        self.out_root = out_root
        self.store = store or Store()
        self.cfg = cfg or LLMConfig.load()
        self.llm_factory = llm_factory or (lambda c: LLMClient(c))
        self.packs: dict[str, KnowledgePack] = {}
        self.window_logical = window_logical
        self.use_cards_directly = use_cards_directly

    def pack_for(self, app: str) -> KnowledgePack:
        """Task cards per app; an app without a card file yet gets an empty pack (LLM Planner only)."""
        if app not in self.packs:
            try:
                self.packs[app] = KnowledgePack(app)
            except FileNotFoundError:
                self.packs[app] = KnowledgePack.empty(app)
        return self.packs[app]

    def create(self, query: str, app_hint: str | None = None,
               progress: Callable[[dict], None] | None = None, cancel_event=None,
               success_check: Expected | None = None) -> CreateResult:
        """success_check: eval-only hook — asserts the task's outcome when the plan has no check of its
        own (LLM-written plans), so eval scores outcomes instead of the model's task naming."""
        t0 = time.monotonic()
        progress = progress or (lambda m: None)
        r = route(query, app_hint)
        if not r.in_scope:
            return CreateResult("text", answer=r.reason, seconds=time.monotonic() - t0)
        app = r.app or "excel"
        pack = self.pack_for(app)

        llm = self.llm_factory(self.cfg)
        if llm is not None:  # hard wall-clock budget for the whole tutorial (< 2 min)
            llm.budget.deadline = t0 + self.cfg.max_seconds
        cached = self.store.get_env(app)
        env, tabs = cached if cached else (None, [])
        qf = fold(query)

        # 1) recipe (0 calls): known question → task, or a confident card match → task
        plan: Plan | None = None
        stored_text: Tutorial | None = None
        source = None
        task = self.store.task_for_question(qf)
        if task is None:
            m = pack.match(query)
            if card_is_clear(m):
                task = m[0][1].id
        if task and env:
            hit = self.store.get_recipe(app, task, env)
            if hit:
                plan, stored_text = hit
                source = "recipe"

        # 2) card or LLM Planner
        if plan is None:
            progress({"state": "PLAN", "message": "Guider đang lập kế hoạch các bước"})
            planner = Planner(pack, llm, app=app, use_cards_directly=self.use_cards_directly,
                              reserve=self.cfg.planner_reserve_s)
            try:
                pr = planner.plan(query, env, tabs)
            except LLMError as e:
                log.warning("service.planner_failed", error=str(e))
                return CreateResult("text", answer="Guider chưa lập được kế hoạch cho câu hỏi này "
                                    "(model trên máy chưa sẵn sàng hoặc trả lời không hợp lệ).",
                                    llm_calls=llm.budget.used if llm else 0, seconds=time.monotonic() - t0,
                                    llm_log=[asdict(c) for c in llm.budget.log] if llm else [])
            if not pr.in_scope or pr.plan is None:
                return CreateResult("text", answer=pr.reason, llm_calls=llm.budget.used if llm else 0,
                                    seconds=time.monotonic() - t0)
            plan, source = pr.plan, pr.source

        if success_check is not None and plan.success_check is None:
            plan = plan.model_copy(update={"success_check": success_check})

        # 3) demonstrate
        def writer(trace, title, tid, status):
            if stored_text is not None and status == "ok" and text_matches_trace(stored_text, trace):
                base = template.write(trace, title, tid, status)
                steps = [b.model_copy(update={"heading": o.heading, "body": o.body, "tip": o.tip})
                         for b, o in zip(base.steps, stored_text.steps)]
                return base.model_copy(update={"title": stored_text.title, "intro": stored_text.intro,
                                               "outro": stored_text.outro, "steps": steps}), "recipe"
            return llm_writer.write(trace, title, tid, status, llm)

        session = Session(plan, self.out_root, progress=progress, window_logical=self.window_logical,
                          writer=writer, disambiguate=LLMDisambiguator(llm) if llm else None,
                          cancel_event=cancel_event, allow_skip=source == "llm")
        res = session.run()

        # 4) remember
        if res.trace is not None:
            self.store.save_env(res.trace.env, res.ribbon_tabs or tabs)
            res.trace.llm_calls = llm.budget.used if llm else 0
            # the session wrote trace.json before the Writer's call was counted; persist the final number
            (res.out_dir / "trace.json").write_text(res.trace.model_dump_json(indent=2), encoding="utf-8")
            if res.tutorial.status == "ok":
                if source != "recipe" or res.writer_source == "llm":  # replay keeps the stored recipe
                    self.store.save_recipe(plan, res.trace, pack.version, res.tutorial)
                self.store.remember_question(qf, plan.task_canonical)
        calls = llm.budget.used if llm else 0
        self.store.add_tutorial(res.tutorial, res.out_dir, calls, source or "?")
        return CreateResult("tutorial", tutorial_id=res.tutorial.tutorial_id, status=res.tutorial.status,
                            path=str(res.out_dir), llm_calls=calls, plan_source=source,
                            writer_source=res.writer_source, seconds=time.monotonic() - t0,
                            llm_log=[asdict(c) for c in llm.budget.log] if llm else [])
