"""Question → tutorial (SPEC §4.2): route → recipe | card | Planner → Session → Writer → recipe store.

LLM budget per tutorial (ADR-5): Planner ≤1 (+repairs), Writer 1, Grounder ≤1, total ≤ max_calls.
Recipe replay: 0 calls (plan from cache, text reused when the grounded steps are identical).
Deferred Writer (ADR-0003): with `on_text_updated`, the tutorial is returned with template text and the
LLM Writer rewrites it in a background thread, then calls back so the app reloads it.
"""
from __future__ import annotations

import json
import threading
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

class _Stopped(Exception):
    pass


def _until_cancel(fn, cancel_event, poll: float = 0.1):
    """Run a blocking call (an LLM request) in a thread; return as soon as the user stops, leaving it behind."""
    box: dict = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as e:  # re-raised in the caller
            box["error"] = e

    t = threading.Thread(target=run, name="cancellable", daemon=True)
    t.start()
    while t.is_alive():
        if cancel_event is not None and cancel_event.is_set():
            raise _Stopped()
        t.join(poll)
    if "error" in box:
        raise box["error"]
    return box["value"]


REWRITE_SECONDS = 90.0  # background Writer: after tutorial.done, outside the 2-minute budget


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
        self._cfg_fixed = cfg is not None  # else re-read per question: the app may switch provider
        self.llm_factory = llm_factory or (lambda c: LLMClient(c))
        self.packs: dict[str, KnowledgePack] = {}
        self.window_logical = window_logical
        self.use_cards_directly = use_cards_directly
        self.background: list[threading.Thread] = []  # deferred Writer threads (joined on shutdown)

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
               success_check: Expected | None = None,
               on_text_updated: Callable[[str], None] | None = None,
               source_file: str | None = None, guard_input: bool = True) -> CreateResult:
        """guard_input: the user touching mouse/keyboard stops the run."""
        import contextlib

        from ..env.input_guard import InputGuard
        cancel_event = cancel_event or threading.Event()
        guard = InputGuard(cancel_event) if guard_input else contextlib.nullcontext()
        with guard:
            res = self._create(query, app_hint, progress, cancel_event, success_check, on_text_updated, source_file)
        if guard_input and guard.reason:
            log.info("service.stopped_by_user_input", reason=guard.reason)
        return res

    def _create(self, query: str, app_hint: str | None, progress: Callable[[dict], None] | None, cancel_event,
                success_check: Expected | None, on_text_updated: Callable[[str], None] | None,
                source_file: str | None) -> CreateResult:
        """success_check: eval-only hook — asserts the task's outcome when the plan has no check of its
        own (LLM-written plans), so eval scores outcomes instead of the model's task naming."""
        t0 = time.monotonic()
        progress = progress or (lambda m: None)
        if source_file:  # the file decides the app (ADR-0003); route() still applies the out-of-scope rules
            from ..sandbox.office import app_for_file
            app_hint = app_for_file(source_file) or app_hint
        r = route(query, app_hint)
        if not r.in_scope:
            return CreateResult("text", answer=r.reason, seconds=time.monotonic() - t0)
        app = r.app or "excel"
        pack = self.pack_for(app)

        if not self._cfg_fixed:
            self.cfg = LLMConfig.load()
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
                pr = _until_cancel(lambda: planner.plan(query, env, tabs), cancel_event)
            except _Stopped:
                return CreateResult("text", answer="Đã dừng theo yêu cầu.", seconds=time.monotonic() - t0)
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
                                               "outro": stored_text.outro, "steps": steps,
                                               "example": (base.example.model_copy(update={"text": stored_text.example.text})
                                                           if base.example and stored_text.example else base.example)}), "recipe"
            if on_text_updated is not None:  # deferred: answer now with the template text
                return template.write(trace, title, tid, status), "template"
            return llm_writer.write(trace, title, tid, status, llm)

        session = Session(plan, self.out_root, progress=progress, window_logical=self.window_logical,
                          writer=writer, disambiguate=LLMDisambiguator(llm) if llm else None,
                          cancel_event=cancel_event, allow_skip=source == "llm", source_file=source_file)
        if cancel_event is not None and cancel_event.is_set():  # stopped between planning and Office start-up
            return CreateResult("text", answer="Đã dừng theo yêu cầu.", seconds=time.monotonic() - t0)
        res = session.run()
        fb = pack.by_id[plan.task_canonical].raw.get("fallback") if plan.task_canonical in pack.by_id else None
        if (fb in pack.by_id and res.tutorial.status not in ("ok", "cancelled")
                and not (cancel_event is not None and cancel_event.is_set())):
            # keyboard way did not work here (e.g. the sandbox could not get the keyboard): show the mouse way
            log.info("service.keyboard_fallback", card=plan.task_canonical, fallback=fb)
            plan = pack.by_id[fb].to_plan()
            source = "card_mouse_fallback"
            session = Session(plan, self.out_root, progress=progress, window_logical=self.window_logical,
                              writer=writer, disambiguate=LLMDisambiguator(llm) if llm else None,
                              cancel_event=cancel_event, allow_skip=False, source_file=source_file)
            res = session.run()

        # 4) remember
        if res.trace is not None:
            self.store.save_env(res.trace.env, res.ribbon_tabs or tabs)
            res.trace.llm_calls = llm.budget.used if llm else 0
            # the session wrote trace.json before the Writer's call was counted; persist the final number
            (res.out_dir / "trace.json").write_text(res.trace.model_dump_json(indent=2), encoding="utf-8")
            if res.tutorial.status == "ok" and not source_file:  # user-file runs skip ref checks: no recipe
                if source != "recipe" or res.writer_source == "llm":  # replay keeps the stored recipe
                    self.store.save_recipe(plan, res.trace, pack.version, res.tutorial)
                self.store.remember_question(qf, plan.task_canonical)
        calls = llm.budget.used if llm else 0
        self.store.add_tutorial(res.tutorial, res.out_dir, calls, source or "?")
        writer_source = res.writer_source
        if (on_text_updated is not None and llm is not None and res.trace is not None and res.trace.steps
                and res.writer_source == "template" and res.tutorial.status != "cancelled"):
            writer_source = "llm_pending"
            t = threading.Thread(target=self._rewrite, name=f"writer-{res.tutorial.tutorial_id}", daemon=True,
                                 args=(res, plan, llm, on_text_updated))
            self.background = [b for b in self.background if b.is_alive()] + [t]
            t.start()
        return CreateResult("tutorial", tutorial_id=res.tutorial.tutorial_id, status=res.tutorial.status,
                            path=str(res.out_dir), llm_calls=calls, plan_source=source,
                            writer_source=writer_source, seconds=time.monotonic() - t0,
                            llm_log=[asdict(c) for c in llm.budget.log] if llm else [])

    def _rewrite(self, res, plan: Plan, llm: LLMClient, on_text_updated: Callable[[str], None]):
        """Deferred Writer: same rules as the inline one (exact labels, template fallback), own time box."""
        import pythoncom
        pythoncom.CoInitializeEx(0)  # same apartment rules as the tutorial workers (no COM used here)
        try:
            llm.budget.deadline = time.monotonic() + REWRITE_SECONDS
            tut, src = llm_writer.write(res.trace, plan.title, res.tutorial.tutorial_id, res.tutorial.status, llm)
            if src != "llm" or template.validate_labels(tut, res.trace):
                log.info("service.rewrite_kept_template", tutorial_id=res.tutorial.tutorial_id)
                return
            (res.out_dir / "tutorial.json").write_text(json.dumps(tut.model_dump(), ensure_ascii=False, indent=2),
                                                       encoding="utf-8")
            res.trace.llm_calls = llm.budget.used
            (res.out_dir / "trace.json").write_text(res.trace.model_dump_json(indent=2), encoding="utf-8")
            if tut.status == "ok":
                self.store.update_recipe_text(plan.app, plan.task_canonical, res.trace.env, tut)
        except Exception as e:  # the template tutorial already stands; never surface this
            log.warning("service.rewrite_failed", error=repr(e))
        finally:  # always tell the app, so its "rewriting" note never hangs (it reloads whatever is on disk)
            try:
                on_text_updated(res.tutorial.tutorial_id)
            except Exception:
                pass
