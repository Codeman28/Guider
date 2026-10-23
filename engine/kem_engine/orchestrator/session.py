"""Orchestrator (SPEC §4.3): SETUP → per step GROUND → CAPTURE → ACT → VERIFY → WRITE, TEARDOWN in finally.

Phase 1: hand-written plans, no LLM. Esc cancels at the next checkpoint.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import structlog

from ..annotate.draw import Style, annotate, smart_crop
from ..annotate.redact import fallback_identity_rect, redact
from ..capture.printwindow import capture_composite
from ..env import win32
from ..env.probe import probe_excel
from ..grounding.grounder import GroundResult, ground, load_aliases
from ..models import Locator, Plan, Rect, Step, Target, Trace, TraceStep, Tutorial
from ..safety.guard import GuardContext, SafetyGuard, SafetyViolation
from ..sandbox import excel
from ..sandbox.com import com_retry, is_busy_error
from ..uia import actuator
from ..uia.snapshot import snapshot
from ..verify.checks import COM_COUNTERS, com_check, poll
from ..writer.template import validate_labels, write

log = structlog.get_logger()

WARNING = "Guider đang làm mẫu trên một file Excel trống — vui lòng đừng gõ phím hay bấm chuột. Nhấn Esc để dừng."
MAX_REPAIRS = 2
MAX_ACT_ATTEMPTS = 2


class Cancelled(Exception):
    pass


class StepFailed(Exception):
    pass


class NotFound(StepFailed):
    """The step's element is not on screen (as opposed to: found but the action did not verify)."""


@dataclass
class RunResult:
    tutorial: Tutorial
    out_dir: Path
    teardown: dict
    seconds: float
    trace: Trace | None = None
    writer_source: str = "template"
    ribbon_tabs: list[str] | None = None


WriteFn = Callable[[Trace, str, str, str], tuple[Tutorial, str]]
Disambiguate = Callable[[Step, list], object]


def _template_writer(trace, title, tid, status):
    return write(trace, title, tid, status), "template"


class Session:
    def __init__(self, plan: Plan, out_root: Path, progress: Callable[[dict], None] | None = None,
                 window_logical: tuple[int, int] = (1280, 800), writer: WriteFn | None = None,
                 disambiguate: Disambiguate | None = None, cancel_event=None, allow_skip: bool = False):
        self.plan = plan
        self.window_logical = window_logical
        self.writer = writer or _template_writer
        self.disambiguate = disambiguate
        self.cancel_event = cancel_event  # threading.Event set by tutorial.cancel (RPC)
        self.ribbon_tabs: list[str] = []
        self.allow_skip = allow_skip  # LLM plans may contain a step this UI does not need
        self._last_expand: Step | None = None
        self._skipped: set[int] = set()
        self.session_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.out_dir = out_root / f"{self.session_id}_{plan.task_canonical}"
        self.progress = progress or (lambda m: None)
        self.aliases = load_aliases()
        self.sb: excel.SandboxHandle | None = None
        self.trace: Trace | None = None
        self.created_files: list[str] = []
        self.style: Style | None = None
        self.scale = 1.0

    # ---- helpers -------------------------------------------------------------------------
    def _emit(self, state: str, message: str, step_i: int = 0):
        if self.trace:
            self.trace.state = state
        self.progress({"session_id": self.session_id, "state": state, "step_i": step_i,
                       "n_steps": len(self.plan.steps), "message": message})

    def _check_cancel(self):
        if win32.escape_pressed() or (self.cancel_event is not None and self.cancel_event.is_set()):
            raise Cancelled()

    def _windows(self) -> list[int]:
        # S3: popups are owned by a hidden window, so whitelist = all windows of our own process.
        wins = excel.sandbox_windows(self.sb)
        return [self.sb.hwnd] + [w for w in wins if w != self.sb.hwnd]

    def _ping_excel(self):
        """S4: if the user typed into the sandbox, Excel sits in cell-edit mode and COM is busy."""
        if len(self._windows()) > 1:
            return  # a popup/dialog of ours is open on purpose
        try:
            com_retry(lambda: self.sb.app.Ready, timeout=1.0)
        except Exception as e:
            if is_busy_error(e):
                log.warning("session.user_input_detected")
                self._emit("RECOVER", "Phát hiện có phím gõ vào cửa sổ mẫu — Guider khôi phục và làm tiếp.")
                excel.unstick(self.sb)
            else:
                raise
        self._restore_selection()

    def _restore_selection(self):
        """A stray click can move the selection; re-apply the plan's range so toggles hit the right cells."""
        if len(self._windows()) > 1:
            return  # a menu or dialog of ours is open; touching the grid would close it
        for pre in self.plan.preconditions:
            try:
                com_retry(lambda: self.sb.doc.ActiveSheet.Range(pre.ref).Select(), timeout=2)
            except Exception as e:
                log.warning("session.restore_selection_failed", error=repr(e))

    def _reopen_last_menu(self) -> bool:
        """Office closes a ribbon menu/gallery when another window takes focus. Re-open it silently."""
        if self._last_expand is None:
            return False
        res, _ = self._ground(self._last_expand)
        if res.element is None:
            return False
        try:
            actuator.perform("expand", res.element)
        except actuator.ActionError:
            return False
        time.sleep(1.0)
        log.info("session.menu_reopened", name=res.element.name)
        return True

    def _save(self, img, name: str) -> str:
        path = self.out_dir / name
        img.save(path, "PNG", optimize=True)
        self.created_files.append(name)
        return name

    def _capture(self, box: Rect | None, step_no: int, identity: list[Rect], name: str) -> str:
        img, (ox, oy) = capture_composite(self.sb.hwnd, self._windows()[1:])
        local_ident = [Rect(left=r.left - ox, top=r.top - oy, right=r.right - ox, bottom=r.bottom - oy)
                       for r in identity] or [fallback_identity_rect(img.width, self.scale)]
        img = redact(img, local_ident)
        if box is not None:
            lb = Rect(left=box.left - ox, top=box.top - oy, right=box.right - ox, bottom=box.bottom - oy)
            img = annotate(img, lb, step_no, self.style)
            img, _ = smart_crop(img, lb, keep_top=round(185 * self.scale), min_w=round(720 * self.scale),
                                margin=round(160 * self.scale))
        return self._save(img, name)

    # ---- steps ---------------------------------------------------------------------------
    def _ground(self, step: Step) -> tuple[GroundResult, list[Rect]]:
        els, ident = snapshot(self._windows())
        return ground(step.target, step.intent, els, self.aliases), ident

    def _verify(self, step: Step, el, dialogs_before: set[int], windows_before: set[int],
                timeout: float | None = None) -> bool:
        exp = step.expected
        ui_t, com_t = timeout or 5.0, timeout or 8.0
        if exp.type == "none":
            return True
        if exp.type == "tab_selected":
            return poll(lambda: actuator.is_selected(el), timeout=ui_t)
        if exp.type == "expanded":
            return poll(lambda: actuator.is_expanded(el) or bool(set(self._windows()) - windows_before),
                        timeout=ui_t)
        if exp.type == "dialog_opened":
            return poll(lambda: bool(set(excel.dialogs(self.sb)) - dialogs_before), timeout=ui_t)
        if exp.type == "dialog_closed":
            return poll(lambda: not (set(excel.dialogs(self.sb)) & dialogs_before), timeout=ui_t)
        if exp.type == "com_check":
            return poll(lambda: com_check(self.sb.doc, exp.prop, exp.ref, exp.op, exp.value), timeout=com_t)
        counter = COM_COUNTERS[exp.type]
        return poll(lambda: counter(self.sb.doc) >= exp.min_count, timeout=com_t)

    def _run_step(self, step: Step, plan_step_id: int | None, reason: str | None = None, repairs: int = 0):
        assert self.trace is not None
        self._check_cancel()
        self._ping_excel()
        n = len(self.trace.steps) + 1
        ts = TraceStep(id=n, plan_step_id=plan_step_id, intent=step.intent, value=step.value,
                       inserted_reason=reason)
        self.trace.steps.append(ts)
        self._emit("GROUND", f"Bước {n}: tìm nút", n)

        res, ident = self._ground(step)
        if res.element is None:
            time.sleep(0.6)  # UI may still be animating
            res, ident = self._ground(step)
        if res.element is None and self._reopen_last_menu():
            res, ident = self._ground(step)
        if res.element is None:
            if res.repair and repairs < MAX_REPAIRS:
                self.trace.steps.pop()
                rep = res.repair
                rstep = Step(id=0, intent=rep.intent,
                             target=Target(names=[rep.element.name], control_type=rep.element.control_type,
                                           automation_id=rep.element.automation_id or None),
                             expected={"type": "expanded"})
                self._run_step(rstep, None, reason=rep.reason, repairs=repairs + 1)
                return self._run_step(step, plan_step_id, reason, repairs + 1)
            ts.error = f"không tìm thấy phần tử (điểm cao nhất {res.score:.0f})"
            raise NotFound(ts.error)

        el = res.element
        if res.ambiguous and self.disambiguate is not None:
            picked = self.disambiguate(step, [c for _, c in res.candidates])
            if picked is not None:
                el = picked
        ts.element_name, ts.control_type, ts.access_key = el.name, el.control_type, el.access_key or None
        ts.grounding_score, ts.ambiguous = res.score, res.ambiguous
        ts.locator = Locator(automation_id=el.automation_id or None, control_type=el.control_type,
                             name=el.name, within=(step.target.within.names[0] if step.target.within else None))
        ts.rect = el.rect

        # Capture before acting so the arrow points at a button not yet pressed — except typed
        # values, which only make sense once they are in the box.
        capture_after = step.intent == "set_value"
        if not capture_after:
            self._emit("CAPTURE", f"Bước {n}: chụp ảnh", n)
            ts.image = self._capture(el.rect, n, ident, f"step_{n:02d}.png")

        for attempt in range(1, MAX_ACT_ATTEMPTS + 1):
            self._check_cancel()
            ts.attempts = attempt
            SafetyGuard(GuardContext(allowed_hwnds=lambda: set(self._windows()),
                                     foreground=win32.foreground)).check(step.intent, el)
            dialogs_before, windows_before = set(excel.dialogs(self.sb)), set(self._windows())
            self._emit("ACT", f"Bước {n}: {step.intent} “{el.name}”", n)
            try:
                actuator.perform(step.intent, el, step.value)
            except actuator.ActionError as e:
                ts.error = str(e)
                log.warning("session.act_failed", step=n, error=str(e))
            self._emit("VERIFY", f"Bước {n}: kiểm tra kết quả", n)
            if self._verify(step, el, dialogs_before, windows_before):
                ts.verified, ts.error = True, None
                break
            if attempt < MAX_ACT_ATTEMPTS:
                # Never blindly repeat: a second toggle undoes the first. Restore the selection, look
                # again, and only act again if the post-condition still does not hold.
                self._restore_selection()
                if self._verify(step, el, dialogs_before, windows_before, timeout=1.0):
                    ts.verified, ts.error = True, None
                    break
                if step.intent != "expand":
                    self._reopen_last_menu()
                res, ident = self._ground(step)
                if res.element is None:
                    break
                el = res.element
        if not ts.verified:
            ts.error = ts.error or f"không xác minh được ({step.expected.type})"
            raise StepFailed(ts.error)
        if capture_after:
            time.sleep(0.3)
            self._emit("CAPTURE", f"Bước {n}: chụp ảnh", n)
            ts.image = self._capture(el.rect, n, ident, f"step_{n:02d}.png")

        self._last_expand = step if step.intent == "expand" else None
        if step.capture_result:
            time.sleep(0.4)
            _, ident = snapshot(self._windows())
            ts.result_image = self._capture(None, n, ident, f"step_{n:02d}_result.png")

    # ---- entry ---------------------------------------------------------------------------
    def run(self) -> RunResult:
        t0 = time.monotonic()
        self.out_dir.mkdir(parents=True, exist_ok=False)
        status = "ok"
        teardown_report: dict = {}
        win32.escape_pressed()  # clear the "pressed since last call" bit
        try:
            self.progress({"session_id": self.session_id, "state": "SETUP", "step_i": 0,
                           "n_steps": len(self.plan.steps), "message": WARNING})
            self.sb = excel.setup(self.plan.fixture_id, size_logical=self.window_logical)
            env = probe_excel(self.sb.app, self.sb.hwnd)
            self.scale = env.dpi / 96
            self.style = Style.load(self.scale)
            self.trace = Trace(session_id=self.session_id, task_canonical=self.plan.task_canonical, env=env)
            for pre in self.plan.preconditions:
                com_retry(lambda: self.sb.doc.ActiveSheet.Range(pre.ref).Select())
            # No foreground juggling: PrintWindow captures covered windows (S3), and Office raises its
            # own window on the first ribbon command anyway (S4). The Alt-key trick showed KeyTips.
            time.sleep(0.5)
            tabs, _ = snapshot([self.sb.hwnd])
            ribbon = [e for e in tabs if e.control_type == "TabItem" and e.name]
            top = min((e.rect.top for e in ribbon), default=0)
            self.ribbon_tabs = [e.name for e in ribbon if e.rect.top <= top + 10]  # drop sheet tabs
            skipped = False
            for i, step in enumerate(self.plan.steps):
                try:
                    self._run_step(step, step.id)
                except NotFound:
                    # An LLM plan may add a step this UI does not have. Skip it (once) only if the next
                    # step's element is on screen right now; never skip in reviewed cards/recipes.
                    nxt = self.plan.steps[i + 1] if i + 1 < len(self.plan.steps) else None
                    if not (self.allow_skip and not skipped and nxt and nxt.target
                            and self._ground(nxt)[0].element is not None):
                        raise
                    skipped = True
                    self._skipped.add(step.id)
                    self.trace.steps.pop()
                    log.warning("session.step_skipped", plan_step=step.id)
            sc = self.plan.success_check
            if sc is not None and not self._verify(Step(id=0, intent="wait_for", expected=sc), None, set(), set()):
                status = "partial"
                log.warning("session.success_check_failed", check=sc.model_dump())
        except Cancelled:
            status = "cancelled"
            self._emit("CANCELLED", "Đã dừng theo yêu cầu.")
        except (StepFailed, SafetyViolation) as e:
            status = "partial" if self.trace and any(s.verified for s in self.trace.steps) else "failed"
            log.warning("session.step_failed", error=str(e))
            if isinstance(e, SafetyViolation) and self.trace and self.trace.steps:
                self.trace.steps[-1].error = f"chặn bởi SafetyGuard: {e}"
        finally:
            if self.sb is not None:
                self._emit("TEARDOWN", "Dọn dẹp file mẫu")
                teardown_report = excel.teardown(self.sb)

        if self.trace is None:
            raise RuntimeError("sandbox setup failed")
        self._add_undemonstrated_steps()
        self._emit("WRITE", "Viết hướng dẫn")
        tut, writer_source = self.writer(self.trace, self.plan.title, self.session_id, status)
        bad = validate_labels(tut, self.trace)
        if bad:  # template writer only uses Trace names; this guards future edits
            raise RuntimeError(f"writer produced labels not in trace: {bad}")
        self._write_json("tutorial.json", tut.model_dump())
        self._write_json("trace.json", self.trace.model_dump())
        self._write_json("manifest.json", {"session_id": self.session_id, "files": self.created_files + ["manifest.json"],
                                           "teardown": teardown_report})
        self._emit("DONE", f"Xong ({status})")
        return RunResult(tut, self.out_dir, teardown_report, time.monotonic() - t0, self.trace, writer_source,
                         self.ribbon_tabs)

    def _add_undemonstrated_steps(self):
        """Plan steps never reached still appear, as text only (SPEC §9 error state)."""
        done = {s.plan_step_id for s in self.trace.steps if s.plan_step_id is not None} | self._skipped
        for step in self.plan.steps:
            if step.id not in done and step.target:
                self.trace.steps.append(TraceStep(id=len(self.trace.steps) + 1, plan_step_id=step.id,
                                                  intent=step.intent, element_name=step.target.names[0],
                                                  control_type=step.target.control_type.split("|")[0],
                                                  value=step.value, error="chưa làm mẫu"))

    def _write_json(self, name: str, data):
        (self.out_dir / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.created_files.append(name)
