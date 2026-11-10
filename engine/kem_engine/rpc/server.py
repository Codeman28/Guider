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

SETTINGS_KEYS = {"provider", "planner_model", "writer_model", "accent", "output_lang", "vision_cloud"}
PROVIDERS = {"ollama", "gemini"}  # choices the app offers (ADR-0003)


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
        if conf is not None and not conf.is_local:
            ok = conf.api_key() is not None
            return {"ok": ok, "provider": cfg.provider, "model": conf.models[0] if conf.models else "",
                    **({} if ok else {"error": "Chưa nhập API key cho " + cfg.provider})}
        if conf is None:
            return {"ok": False, "provider": cfg.provider, "error": "Provider không có trong cấu hình"}
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
            "tutorial.delete": self.tutorial_delete,
            "settings.get": self.settings_get, "settings.set": self.settings_set,
            "system.check": self.system_check,
            "settings.set_api_key": self.settings_set_api_key, "settings.check_cloud": self.settings_check_cloud,
            "training.status": self.training_status, "training.start": self.training_start,
            "training.cancel": self.training_cancel, "training.memory": self.training_memory,
            "training.remove": self.training_remove, "training.ask": self.training_ask,
            "problem.paste": self.problem_paste, "problem.capture": self.problem_capture,
            "problem.prepare": self.problem_prepare,
            "tutorial.image": self.tutorial_image, "problem.image": self.problem_image,
            "problem.windows": self.problem_windows, "problem.warm_up": self.problem_warm_up,
        }
        self._training: dict | None = None  # {"job_id", "cancel", "thread"} — one training run at a time

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
        source_file = params.get("source_file")
        if source_file is not None:
            from ..sandbox.office import app_for_file
            if not isinstance(source_file, str) or app_for_file(source_file) is None or not Path(source_file).is_file():
                raise RpcError(INVALID_PARAMS, "Chỉ chọn được file Excel, Word hoặc PowerPoint có trên máy.")
        mode = params.get("mode", "guide")
        if mode not in ("guide", "exercise"):
            raise RpcError(INVALID_PARAMS, "mode must be guide or exercise")
        problem_image = params.get("problem_image")
        if mode == "exercise" and not problem_image:
            raise RpcError(INVALID_PARAMS, "Chế độ Giải bài tập cần ảnh bài tập.")
        if problem_image is not None:
            from ..vision.problem import is_image
            if not isinstance(problem_image, str) or not is_image(problem_image) or not Path(problem_image).is_file():
                raise RpcError(INVALID_PARAMS, "Chỉ gửi được ảnh PNG, JPG, BMP, GIF hoặc WEBP có trên máy.")
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
                updated = lambda tid: self.notify("tutorial.updated", {"tutorial_id": tid})  # noqa: E731
                if mode == "exercise":
                    res = self.service.create_exercise(problem_image, query, progress=progress, cancel_event=cancel,
                                                       on_text_updated=updated)
                elif problem_image:
                    res = self.service.create_from_problem(problem_image, query, source_file=source_file,
                                                           progress=progress, cancel_event=cancel,
                                                           on_text_updated=updated)
                else:
                    res = self.service.create(query, params.get("app_hint"), progress=progress, cancel_event=cancel,
                                              source_file=source_file, on_text_updated=updated)
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

    # ---- picture of the problem (ADR-0005): everything stays on this machine
    def _inbox(self) -> Path:
        import uuid

        from ..sandbox.office import work_root
        return work_root() / "inbox" / uuid.uuid4().hex[:12]

    def problem_paste(self, params):
        """An image pasted into the chat: {data_b64} → {path} of a PNG in the local work folder."""
        from ..vision import problem as vp
        data = params.get("data_b64")
        if not isinstance(data, str) or not data:
            raise RpcError(INVALID_PARAMS, "data_b64 is required")
        try:
            work = self._inbox()
            return {"path": str(vp.prepare(vp.save_pasted(data, work), work))}
        except vp.ProblemError as e:
            raise RpcError(INVALID_PARAMS, str(e)) from e

    def problem_prepare(self, params):
        """A picture the user picked in the Open dialog: copied (shrunk) into the local inbox; original untouched."""
        from ..vision import problem as vp
        path = params.get("path")
        if not isinstance(path, str):
            raise RpcError(INVALID_PARAMS, "path is required")
        try:
            return {"path": str(vp.prepare(path, self._inbox()))}
        except vp.ProblemError as e:
            raise RpcError(INVALID_PARAMS, str(e)) from e

    def problem_windows(self, params):
        from ..vision import problem as vp
        return vp.office_windows()

    def problem_capture(self, params):
        """Screenshot of the user's front-most Office window (or {hwnd}); the user clicked to allow it."""
        from ..vision import problem as vp
        try:
            path, w = vp.capture_office(self._inbox(), params.get("hwnd"))
        except vp.ProblemError as e:
            raise RpcError(INVALID_PARAMS, str(e)) from e
        return {"path": str(path), "app": w["app"], "title": w["title"]}

    def problem_warm_up(self, params):
        """Load the local vision model in the background as soon as a picture is attached."""
        from ..vision import problem as vp
        threading.Thread(target=vp.warm_up, name="vision-warm-up", daemon=True).start()
        return {"ok": True}

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
            data["trace"] = {"env": t.get("env"), "llm_calls": t.get("llm_calls"), "user_file": t.get("user_file", False),
                             "steps": [{k: s.get(k) for k in ("id", "intent", "element_name", "control_type",
                                                             "verified", "attempts", "grounding_score",
                                                             "inserted_reason", "error", "verify_note")}
                                       for s in t.get("steps", [])]}
        return data

    @staticmethod
    def _data_url(path: Path) -> dict:
        import base64
        kind = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg"}.get(path.suffix.lower())
        if kind is None or not path.is_file():
            raise RpcError(INVALID_PARAMS, "no such image")
        return {"data_url": f"data:image/{kind};base64," + base64.b64encode(path.read_bytes()).decode()}

    def tutorial_image(self, params):
        """A tutorial's screenshot as a data URL. The app showed images through Tauri's asset protocol, which
        answered 403 for files inside its own scope on the installed build (10/11/2026); the engine already
        owns these files, so it hands them over. Only plain file names inside that tutorial's folder."""
        name = params.get("file")
        if not isinstance(name, str) or not name or Path(name).name != name:
            raise RpcError(INVALID_PARAMS, "file must be a plain file name")
        return self._data_url(self._dir(params.get("tutorial_id")) / name)

    def problem_image(self, params):
        """Thumbnail of a picture attached in the chat: only files inside the local inbox."""
        from ..sandbox.office import work_root
        path = params.get("path")
        if not isinstance(path, str):
            raise RpcError(INVALID_PARAMS, "path is required")
        p, inbox = Path(path).resolve(), (work_root() / "inbox").resolve()
        if inbox not in p.parents:
            raise RpcError(INVALID_PARAMS, "not an attached picture")
        return self._data_url(p)

    def tutorial_list(self, params):
        out = []
        for m in self.service.store.list_tutorials():
            p = Path(m["path"])
            m["bytes"] = sum(f.stat().st_size for f in p.iterdir() if f.is_file()) if p.is_dir() else 0
            out.append(m)
        return out

    def tutorial_delete(self, params):
        """Free disk space. Deletes only what the tutorial made: the files listed in
        its manifest plus its exports (SPEC §8), inside the tutorials folder; then the library entry."""
        ids = params.get("tutorial_ids") or ([params["tutorial_id"]] if params.get("tutorial_id") else [])
        if not ids or not all(isinstance(i, str) for i in ids):
            raise RpcError(INVALID_PARAMS, "tutorial_id(s) required")
        root = self.out_root.resolve()
        freed, deleted = 0, []
        for tid in ids:
            p = self.service.store.tutorial_path(tid)
            if p is None:
                continue
            p = p.resolve()
            if p.is_dir() and root in p.parents:
                manifest = p / "manifest.json"
                files = json.loads(manifest.read_text(encoding="utf-8")).get("files", []) if manifest.exists() else []
                for name in set(files) | {"tutorial.md", "tutorial.html", "manifest.json"}:
                    f = (p / name).resolve()
                    if f.parent == p and f.is_file():
                        freed += f.stat().st_size
                        f.unlink()
                try:
                    p.rmdir()  # only if nothing else is left in it
                except OSError:
                    pass
            self.service.store.remove_tutorial(tid)
            deleted.append(tid)
        return {"deleted": deleted, "freed_bytes": freed}

    def tutorial_export(self, params):
        from .export import export
        try:
            return {"path": str(export(self._dir(params.get("tutorial_id")), params.get("format", "md")))}
        except ValueError as e:
            raise RpcError(INVALID_PARAMS, str(e)) from e

    def settings_get(self, params):
        from ..llm.secrets import has_key
        cur = json.loads(self.settings_path.read_text(encoding="utf-8")) if self.settings_path.exists() else {}
        return {**cur, "has_key": {p: has_key(p) for p in PROVIDERS - {"ollama"}}}  # never the key itself

    def settings_set(self, params):
        bad = set(params) - SETTINGS_KEYS
        if bad:
            raise RpcError(INVALID_PARAMS, f"unknown settings: {sorted(bad)}")
        if "vision_cloud" in params and not isinstance(params["vision_cloud"], bool):
            raise RpcError(INVALID_PARAMS, "vision_cloud must be true or false")
        if "provider" in params and params["provider"] not in PROVIDERS:
            raise RpcError(INVALID_PARAMS, f"unknown provider: {params['provider']}")
        cur = self.settings_get({})
        cur.pop("has_key", None)
        cur.update(params)
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.settings_get({})

    def settings_set_api_key(self, params):
        """The user pastes their own key; stored with DPAPI, never echoed back or logged."""
        from ..llm.secrets import set_key
        provider, key = params.get("provider"), params.get("key")
        if provider not in PROVIDERS - {"ollama"}:
            raise RpcError(INVALID_PARAMS, "unknown cloud provider")
        if key is not None and (not isinstance(key, str) or len(key) > 512):
            raise RpcError(INVALID_PARAMS, "invalid key")
        set_key(provider, key)
        return {"ok": True}

    def settings_check_cloud(self, params):
        """One tiny call to the cloud provider (no user data) so the app can say whether the key works."""
        import time

        from pydantic import BaseModel

        from ..llm.client import Budget, LLMClient
        from ..llm.config import LLMConfig
        from ..llm.providers.openai_compat import OpenAICompatProvider

        class Ping(BaseModel):
            ok: bool

        provider = params.get("provider", "gemini")
        cfg = LLMConfig.load()
        conf = cfg.providers.get(provider)
        if conf is None or conf.is_local:
            raise RpcError(INVALID_PARAMS, "unknown cloud provider")
        client = LLMClient(cfg, providers=[OpenAICompatProvider(conf)], budget=Budget(2))
        t0 = time.monotonic()
        try:
            client.complete("writer", "Trả JSON {\"ok\": true}.", {"ping": True}, Ping, max_repairs=0)
            return {"ok": True, "model": conf.models[0] if conf.models else "", "seconds": round(time.monotonic() - t0, 1)}
        except Exception as e:
            return {"ok": False, "error": str(e)[:300]}

    # ---- training area (ADR-0004, developer-only) -----------------------------------------
    @staticmethod
    def training_available() -> bool:
        """Only when the engine runs from the repository: learned cards go into engine/knowledge for git."""
        import os
        from ..intent.knowledge import KNOWLEDGE_DIR
        return not getattr(sys, "frozen", False) and os.access(KNOWLEDGE_DIR, os.W_OK)

    def _need_training(self):
        if not self.training_available():
            raise RpcError(INVALID_REQUEST, "Khu Huấn luyện chỉ có ở bản dành cho nhà phát triển.")

    def training_status(self, params):
        if not self.training_available():
            return {"available": False}
        from ..training.llm import TrainingLLM
        llm = TrainingLLM()
        t = self._training
        return {"available": True, "model": llm.label, "cloud": llm.cloud, "research": bool(llm.gemini_key),
                "running": bool(t and t["thread"].is_alive()), "job_id": t["job_id"] if t else None}

    def training_start(self, params):
        self._need_training()
        kind, ref = params.get("kind"), params.get("ref") or ""
        if kind not in ("file", "link", "research", "verify", "refit") or not isinstance(ref, str):
            raise RpcError(INVALID_PARAMS, "kind must be file, link, research, verify or refit")
        if kind in ("file", "link") and not ref.strip():
            raise RpcError(INVALID_PARAMS, "ref is required")
        if self._training and self._training["thread"].is_alive():
            raise RpcError(BUSY, "Đang huấn luyện một nguồn khác. Chờ xong hoặc dừng trước.")
        import uuid
        job_id = uuid.uuid4().hex[:10]
        cancel = threading.Event()

        def progress(m: dict):
            self.notify("training.progress", {"job_id": job_id, **m})

        def work():
            import pythoncom
            pythoncom.CoInitializeEx(0)
            try:
                from ..training.job import TrainingJob
                stats = TrainingJob(kind, ref.strip(), self.out_root, progress, self._lock, cancel,
                                    demonstrate=bool(params.get("demonstrate", True))).run()
                self.notify("training.done", {"job_id": job_id, "ok": True, **stats})
            except Exception as e:
                traceback.print_exc(file=sys.stderr)
                self.notify("training.done", {"job_id": job_id, "ok": False, "error": str(e)[:400]})

        t = threading.Thread(target=work, name=f"training-{job_id}", daemon=True)
        self._training = {"job_id": job_id, "cancel": cancel, "thread": t}
        t.start()
        return {"job_id": job_id}

    def training_cancel(self, params):
        t = self._training
        if t and t["job_id"] == params.get("job_id"):
            t["cancel"].set()
            return {"ok": True}
        return {"ok": False}

    def training_memory(self, params):
        self._need_training()
        from ..training.memory import Memory
        return Memory().overview()

    def training_remove(self, params):
        self._need_training()
        from ..training.memory import APPS, Memory
        m, kind, item = Memory(), params.get("kind"), params.get("id", "")
        if kind == "note":
            return {"ok": m.remove_note(item)}
        if kind == "card" and params.get("app") in APPS:
            return {"ok": m.remove_card(params["app"], item)}
        raise RpcError(INVALID_PARAMS, "kind must be card (with app) or note")

    def training_ask(self, params):
        self._need_training()
        q = params.get("question")
        if not isinstance(q, str) or not q.strip():
            raise RpcError(INVALID_PARAMS, "question is required")
        from ..llm.providers.base import LLMError
        from ..training.job import ask
        try:
            return ask(q.strip())
        except LLMError as e:
            return {"answer": f"Chưa trả lời được: {e}", "citations": []}

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
        if self._training:
            self._training["cancel"].set()
            self._training["thread"].join(timeout)
        for t in self.workers:
            t.join(timeout)
        for t in getattr(self._service, "background", []):  # deferred Writer: brief grace, never blocks quit
            t.join(5.0)


def main():
    import logging

    import structlog
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
                        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO))
    for stream in (sys.stdin, sys.stdout, sys.stderr):  # logs in Vietnamese go to stderr
        stream.reconfigure(encoding="utf-8")
    from ..env import runtime
    runtime.init()
    from ..cli import default_out
    from ..orchestrator.service import TutorialService
    out = default_out()
    threading.Thread(target=warm_up_model, name="warm-up", daemon=True).start()
    try:  # Phase 5: close sandboxes a crashed previous run left behind (only provably ours)
        from ..sandbox.recovery import recover
        recover()
    except Exception:
        traceback.print_exc(file=sys.stderr)
    Server(lambda: TutorialService(out), out).serve()


def warm_up_model():
    """Load the local model while the user reads the screen, so the first question does not pay the
    cold-load time (part of the < 2 minute budget). Failures are irrelevant here."""
    try:
        from ..llm.config import LLMConfig
        from ..llm.providers.ollama import OllamaProvider
        cfg = LLMConfig.load()
        conf = cfg.providers.get(cfg.provider)
        if conf is not None and conf.is_local and conf.enabled:
            OllamaProvider(conf).warm_up(cfg.writer_model)
    except Exception:
        pass


if __name__ == "__main__":
    main()
