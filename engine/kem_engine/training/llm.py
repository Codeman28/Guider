"""LLM access for the training area (ADR-0004): Gemini when a key is saved, else a larger local model.

Unlike the tutorial client (llm/client.py) there is no per-tutorial budget and no sanitizer: the payload is the
developer's own training material, never a user's file or screenshot.
"""
from __future__ import annotations

import json
import threading
import time
import tomllib
import urllib.request
from dataclasses import dataclass, replace
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ..llm.config import DEFAULT_PATH, LLMConfig
from ..llm.providers.base import LLMError, LLMTimeout, ProviderUnavailable, QuotaExceeded

M = TypeVar("M", bound=BaseModel)


@dataclass
class TrainingConf:
    cloud_model: str = "gemini-3.5-flash-lite"
    local_model: str = "qwen3:4b"
    chunk_chars_cloud: int = 12000
    chunk_chars_local: int = 3000
    local_num_ctx: int = 8192
    workers_cloud: int = 4
    cloud_rpm: int = 25  # free tier: ~30 requests in 20 s got HTTP 429 (26/10/2026); stay under it
    max_pages: int = 20
    local_timeout_s: float = 600.0
    cloud_timeout_s: float = 60.0

    @classmethod
    def load(cls) -> "TrainingConf":
        raw = tomllib.loads(DEFAULT_PATH.read_text(encoding="utf-8")).get("training", {})
        return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})


class _Pacer:
    """At most `rpm` request starts in any 60 s window, shared by all worker threads."""

    def __init__(self, rpm: int):
        self.rpm = max(1, rpm)
        self.starts: list[float] = []
        self.lock = threading.Lock()

    def wait(self):
        while True:
            with self.lock:
                now = time.monotonic()
                self.starts = [t for t in self.starts if now - t < 60]
                if len(self.starts) < self.rpm:
                    self.starts.append(now)
                    return
                delay = 60 - (now - self.starts[0]) + 0.05
            time.sleep(delay)


class TrainingLLM:
    """With a Gemini key: Gemini only (26/10/2026 — silently falling back to the local model mid-book turned a
    one-minute read into hours). Without a key: the local model."""

    CLOUD_DOWN_AFTER = 5  # consecutive failed chunks before the run stops and says so

    def __init__(self, conf: TrainingConf | None = None):
        from ..llm.providers.ollama import OllamaProvider
        from ..llm.providers.openai_compat import OpenAICompatProvider
        self.conf = conf or TrainingConf.load()
        cfg = LLMConfig.load()
        self.providers: list[tuple[object, str]] = []
        g = cfg.providers.get("gemini")
        self.gemini_key = g.api_key() if g is not None else None
        if self.gemini_key:
            gconf = replace(g, models=[self.conf.cloud_model], timeout_s=self.conf.cloud_timeout_s, enabled=True)
            self.providers.append((OpenAICompatProvider(gconf), self.conf.cloud_model))
        else:
            o = cfg.providers.get("ollama")
            if o is not None:
                self.providers.append((OllamaProvider(replace(o, timeout_s=self.conf.local_timeout_s,
                                                              num_ctx=self.conf.local_num_ctx)), self.conf.local_model))
        self.calls = 0
        self._lock = threading.Lock()  # chunks are read in parallel
        self._failures = 0
        self._pacer = _Pacer(self.conf.cloud_rpm) if self.cloud else None
        self.cloud_down: str | None = None  # set when the cloud model keeps failing: the job stops and reports

    @property
    def cloud(self) -> bool:
        return bool(self.providers) and not getattr(self.providers[0][0], "is_local", True)

    @property
    def label(self) -> str:
        return self.providers[0][1] if self.providers else "không có model"

    @property
    def chunk_chars(self) -> int:
        return self.conf.chunk_chars_cloud if self.cloud else self.conf.chunk_chars_local

    @property
    def workers(self) -> int:
        return max(1, self.conf.workers_cloud) if self.cloud else 1  # one local model = one at a time

    def complete(self, system: str, user: str, out: type[M], max_tokens: int = 4000) -> M:
        schema = out.model_json_schema()
        errors = []
        for provider, model in list(self.providers):
            local = getattr(provider, "is_local", True)
            timeout = None
            for attempt in range(4):
                try:
                    if self._pacer is not None:
                        self._pacer.wait()
                    with self._lock:
                        self.calls += 1
                    sys_prompt = system if attempt == 0 else system + " Lần trước JSON sai; chỉ trả JSON đúng schema."
                    text = provider.complete_json(model, sys_prompt, user, schema, temperature=0.2,
                                                  max_tokens=max_tokens, timeout=timeout)
                    result = out.model_validate_json(text)
                    with self._lock:
                        self._failures = 0
                    return result
                except ValidationError as e:
                    errors.append(f"{model}: JSON sai ({str(e)[:120]})")
                except QuotaExceeded:  # free-tier rate limit: the window is a minute — wait, then retry
                    errors.append(f"{model}: hết lượt tạm thời")
                    time.sleep(30 * (attempt + 1))
                except LLMTimeout as e:  # a slow answer: one more try with twice the time
                    errors.append(f"{model}: {e}")
                    timeout = (self.conf.local_timeout_s if local else self.conf.cloud_timeout_s) * 2
                except (ProviderUnavailable, LLMError) as e:
                    errors.append(f"{model}: {e}")
                    break
        with self._lock:
            self._failures += 1
            if self.cloud and self._failures >= self.CLOUD_DOWN_AFTER and not self.cloud_down:
                self.cloud_down = errors[-1][:160] if errors else "không rõ lỗi"
        raise LLMError("; ".join(errors[-3:]) or "chưa có model nào dùng được")


def search_web(topic: str, api_key: str, model: str, max_results: int = 8, timeout: float = 60) -> list[dict]:
    """Research (ADR-0004): ask Gemini with Google Search grounding; return [{title, url}] of the sources it used.
    The URLs may be Google redirect links; fetching follows the redirect to the real page."""
    body = {
        "contents": [{"role": "user", "parts": [{"text":
            "Tìm các trang hướng dẫn thao tác từng bước (bấm tab nào, nút nào) trên Microsoft 365 desktop cho chủ đề: "
            f"{topic}. Ưu tiên support.microsoft.com và các trang hướng dẫn tiếng Việt uy tín. Liệt kê ngắn gọn."}]}],
        "tools": [{"google_search": {}}],
    }
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        json.dumps(body).encode(), {"Content-Type": "application/json", "x-goog-api-key": api_key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    out, seen = [], set()
    for cand in data.get("candidates", []):
        for ch in (cand.get("groundingMetadata") or {}).get("groundingChunks", []):
            web = ch.get("web") or {}
            uri = web.get("uri")
            if uri and uri not in seen:
                seen.add(uri)
                out.append({"title": web.get("title") or uri, "url": uri})
    return out[:max_results]
