"""LLM access for the training area (ADR-0004): Gemini when a key is saved, else a larger local model.

Unlike the tutorial client (llm/client.py) there is no per-tutorial budget and no sanitizer: the payload is the
developer's own training material, never a user's file or screenshot.
"""
from __future__ import annotations

import json
import tomllib
import urllib.request
from dataclasses import dataclass, replace
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ..llm.config import DEFAULT_PATH, LLMConfig
from ..llm.providers.base import LLMError

M = TypeVar("M", bound=BaseModel)


@dataclass
class TrainingConf:
    cloud_model: str = "gemini-3.8-flash"
    local_model: str = "qwen3:4b"
    chunk_chars_cloud: int = 12000
    chunk_chars_local: int = 4000
    max_pages: int = 20
    local_timeout_s: float = 900.0
    cloud_timeout_s: float = 120.0

    @classmethod
    def load(cls) -> "TrainingConf":
        raw = tomllib.loads(DEFAULT_PATH.read_text(encoding="utf-8")).get("training", {})
        return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})


class TrainingLLM:
    def __init__(self, conf: TrainingConf | None = None):
        from ..llm.providers.ollama import OllamaProvider
        from ..llm.providers.openai_compat import OpenAICompatProvider
        self.conf = conf or TrainingConf.load()
        cfg = LLMConfig.load()
        self.providers: list[tuple[object, str]] = []
        g = cfg.providers.get("gemini")
        if g is not None and g.api_key():
            gconf = replace(g, models=[self.conf.cloud_model], timeout_s=self.conf.cloud_timeout_s, enabled=True)
            self.providers.append((OpenAICompatProvider(gconf), self.conf.cloud_model))
        o = cfg.providers.get("ollama")
        if o is not None:
            self.providers.append((OllamaProvider(replace(o, timeout_s=self.conf.local_timeout_s)), self.conf.local_model))
        self.calls = 0
        self.gemini_key = g.api_key() if g is not None else None

    @property
    def cloud(self) -> bool:
        return bool(self.providers) and not getattr(self.providers[0][0], "is_local", True)

    @property
    def label(self) -> str:
        return self.providers[0][1] if self.providers else "không có model"

    @property
    def chunk_chars(self) -> int:
        return self.conf.chunk_chars_cloud if self.cloud else self.conf.chunk_chars_local

    def complete(self, system: str, user: str, out: type[M], max_tokens: int = 6000) -> M:
        schema = out.model_json_schema()
        errors = []
        for provider, model in self.providers:
            text = ""
            for attempt in range(2):
                try:
                    self.calls += 1
                    sys_prompt = system if attempt == 0 else system + " Lần trước JSON sai; chỉ trả JSON đúng schema."
                    text = provider.complete_json(model, sys_prompt, user, schema, temperature=0.2,
                                                  max_tokens=max_tokens)
                    return out.model_validate_json(text)
                except ValidationError as e:
                    errors.append(f"{model}: JSON sai ({str(e)[:120]})")
                except LLMError as e:
                    errors.append(f"{model}: {e}")
                    break  # provider down / quota: next provider
        raise LLMError("; ".join(errors) or "chưa có model nào dùng được")


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
