"""JSON-RPC 2.0 over stdin/stdout, one JSON object per line (SPEC ADR-6, §11). No network port.

stdout carries protocol messages only; logs go to stderr. One tutorial at a time (one Office sandbox).
"""
from __future__ import annotations

import json
import sys
import threading
import traceback
from pathlib import Path
from typing import Any, Callable

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL = -32700, -32600, -32601, -32602, -32603
BUSY = -32001

SETTINGS_KEYS = {"provider", "planner_model", "writer_model", "accent", "output_lang"}


class RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def check_model() -> dict:
    """Is the configured local model reachable and pulled? Never raises."""
    import urllib.request
    from ..llm.config import LLMConfig
    try:
        cfg = LLMConfig.load()
        conf = cfg.providers.get(cfg.provider)
        if conf is None or not conf.is_local:
            return {"ok": True, "provider": cfg.provider, "note": "cloud provider"}
        with urllib.request.urlopen(conf.base_url.rstrip("/") + "/api/tags", timeout=3) as r:
            names = {m["name"] for m in json.loads(r.read()).get("models", [])}
        wanted = {cfg.planner_model, cfg.writer_model}
        missing = sorted(w for w in wanted if w not in names)
        return {"ok": not missing, "provider": cfg.provider, "model": cfg.writer_model, "missing": missing}
    except Exception as e:
        return {"ok": False, "provider": "ollama", "error": f"Không kết nối được model trên máy: {e}"}


class Server:
    def __init__(self, service_factory: Callable[[], Any], out_root: Path, write: Callable[[str], None] | None = None,
                 settings_path: Path | None = None):
        self._service_factory = service_factory
        self._service = None
        self.out_root = out_root
        self._write = write or self._stdout
        self._lock = threading.Lock()
        self._out_lock = threading.Lock()
        self.active: dict[str, threading.Event] = {}
        self.workers: list[threading.Thread] = []
        self.settings_path = settings_path or out_root.parent / "settings.json"
        self.methods = {
            "env.probe": self.env_probe, "tutorial.create": self.tutorial_create,
            "tutorial.cancel": self.tutorial_cancel, "tutorial.get": self.tutorial_get,
            "tutorial.list": self.tutorial_list, "tutorial.export": self.tutorial_export,
            "settings.get": self.settings_get, "settings.set": self.settings_set,
            "system.check": self.system_check,
        }

    @staticmethod
    def _stdout(line: str):
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    def send(self, obj: dict):
        with self._out_lock:
            self._write(json.dumps(obj, ensure_ascii=False))

    def notify(self, method: str, params: dict):
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    @property
    def service(self):
        if self._service is None:
            self._service = self._service_factory()
        return self._service

    # ---- methods ---------------------------------------------------------------------------
    def env_probe(self, params):
        cached = self.service.store.get_env("excel")
        if cached and not params.get("refresh"):
            return cached[0].model_dump()
        from ..env.probe import probe_excel
        from ..sandbox import excel
        if not self._lock.acquire(blocking=False):
            raise RpcError(BUSY, "Guider đang bận làm mẫu")
        try:
            sb = excel.setup(None)
            try:
                env = probe_excel(sb.app, sb.hwnd)
            finally:
                excel.teardown(sb)
            self.service.store.save_env(env, cached[1] if cached else [])
            return env.model_dump()
        finally:
            self._lock.release()

    def system_check(self, params):
        """First-run machine check (consent screen): Excel via a short sandbox probe, local model via Ollama."""
        out = {"excel": {"ok": False}, "model": {"ok": False}}
        try:
            env = self.env_probe({"refresh": bool(params.get("refresh"))})
            out["excel"] = {"ok": True, "version": env["office_version"], "build": env["office_build"],
                            "ui_lang": env["ui_lang"]}
        except RpcError:
            raise
        except Exception as e:
            out["excel"]["error"] = f"Không mở được Excel: {e}"
        out["model"] = check_model()
        return out

    def tutorial_create(self, params):
        query = params.get("query")
        if not isinstance(query, str) or not query.strip():
            raise RpcError(INVALID_PARAMS, "query is required")
        if not self._lock.acquire(blocking=False):
            raise RpcError(BUSY, "Guider đang làm mẫu một tutorial khác")
        import uuid
        sid = uuid.uuid4().hex[:12]
        cancel = threading.Event()
        self.active[sid] = cancel

        def progress(m: dict):
            self.notify("tutorial.progress", {"session_id": sid, **{k: m.get(k) for k in
                        ("state", "step_i", "n_steps", "message", "label", "intent", "seconds") if k in m}})

        def work():
            import pythoncom
            pythoncom.CoInitializeEx(0)  # COINIT_MULTITHREADED — same apartment as the UIA stack
            try:
                res = self.service.create(query, params.get("app_hint"), progress=progress, cancel_event=cancel)
                self.notify("tutorial.done", {"session_id": sid, **res.to_dict()})
            except Exception as e:  # report, never crash the server
                traceback.print_exc(file=sys.stderr)
                self.notify("tutorial.done", {"session_id": sid, "kind": "error", "answer": str(e)})
            finally:
                self.active.pop(sid, None)
                self._lock.release()

        t = threading.Thread(target=work, name=f"tutorial-{sid}", daemon=True)
        self.workers.append(t)
        t.start()
        return {"session_id": sid}

    def tutorial_cancel(self, params):
        ev = self.active.get(params.get("session_id", ""))
        if ev:
            ev.set()
        return {"ok": ev is not None}

    def _dir(self, tutorial_id: str) -> Path:
        p = self.service.store.tutorial_path(tutorial_id or "")
        if p is None or not (p / "tutorial.json").exists():
            raise RpcError(INVALID_PARAMS, "unknown tutorial_id")
        return p

    def tutorial_get(self, params):
        p = self._dir(params.get("tutorial_id"))
        data = json.loads((p / "tutorial.json").read_text(encoding="utf-8"))
        data["dir"] = str(p)
        trace = p / "trace.json"
        if trace.exists():  # "Xem Guider đã làm gì" (SPEC §8): what was clicked, verified, retried
            t = json.loads(trace.read_text(encoding="utf-8"))
            data["trace"] = {"env": t.get("env"), "llm_calls": t.get("llm_calls"),
                             "steps": [{k: s.get(k) for k in ("id", "intent", "element_name", "control_type",
                                                             "verified", "attempts", "grounding_score",
                                                             "inserted_reason", "error")} for s in t.get("steps", [])]}
        return data

    def tutorial_list(self, params):
        return self.service.store.list_tutorials()

    def tutorial_export(self, params):
        from .export import export
        try:
            return {"path": str(export(self._dir(params.get("tutorial_id")), params.get("format", "md")))}
        except ValueError as e:
            raise RpcError(INVALID_PARAMS, str(e)) from e

    def settings_get(self, params):
        if self.settings_path.exists():
            return json.loads(self.settings_path.read_text(encoding="utf-8"))
        return {}

    def settings_set(self, params):
        bad = set(params) - SETTINGS_KEYS
        if bad:
            raise RpcError(INVALID_PARAMS, f"unknown settings: {sorted(bad)}")
        cur = self.settings_get({})
        cur.update(params)
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
        return cur

    # ---- dispatch --------------------------------------------------------------------------
    def handle_line(self, line: str):
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            return self.send({"jsonrpc": "2.0", "id": None, "error": {"code": PARSE_ERROR, "message": "parse error"}})
        if not isinstance(req, dict) or req.get("jsonrpc") != "2.0" or not isinstance(req.get("method"), str):
            return self.send({"jsonrpc": "2.0", "id": req.get("id") if isinstance(req, dict) else None,
                              "error": {"code": INVALID_REQUEST, "message": "invalid request"}})
        rid = req.get("id")
        fn = self.methods.get(req["method"])
        try:
            if fn is None:
                raise RpcError(METHOD_NOT_FOUND, f"method not found: {req['method']}")
            params = req.get("params") or {}
            if not isinstance(params, dict):
                raise RpcError(INVALID_PARAMS, "params must be an object")
            result = fn(params)
            if rid is not None:
                self.send({"jsonrpc": "2.0", "id": rid, "result": result})
        except RpcError as e:
            if rid is not None:
                self.send({"jsonrpc": "2.0", "id": rid, "error": {"code": e.code, "message": str(e)}})
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            if rid is not None:
                self.send({"jsonrpc": "2.0", "id": rid, "error": {"code": INTERNAL, "message": str(e)}})

    def serve(self, stdin=None):
        for line in (stdin or sys.stdin):
            line = line.strip()
            if line:
                self.handle_line(line)
        self.shutdown()

    def shutdown(self, timeout: float = 60.0):
        """stdin closed (the app quit): cancel running demonstrations and wait for their teardown, so no
        sandbox Excel is left behind (SPEC §8)."""
        for ev in list(self.active.values()):
            ev.set()
        for t in self.workers:
            t.join(timeout)


def main():
    import logging

    import structlog
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
                        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO))
    for stream in (sys.stdin, sys.stdout):
        stream.reconfigure(encoding="utf-8")
    from ..env import runtime
    runtime.init()
    from ..cli import default_out
    from ..orchestrator.service import TutorialService
    out = default_out()
    Server(lambda: TutorialService(out), out).serve()


if __name__ == "__main__":
    main()
