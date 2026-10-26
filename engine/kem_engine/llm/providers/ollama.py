"""Ollama native /api/chat with `format` = JSON schema (structured outputs; S7: 100% schema-valid)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from ..config import ProviderConf
from .base import LLMError, LLMTimeout, ProviderUnavailable


class OllamaProvider:
    name = "ollama"
    is_local = True
    supports_json_schema = True

    def __init__(self, conf: ProviderConf):
        self.base = conf.base_url.rstrip("/")
        self.timeout = conf.timeout_s
        self.think = conf.think
        self.keep_alive = conf.keep_alive
        self.num_ctx = conf.num_ctx

    def _post(self, body: dict, timeout: float) -> dict:
        req = urllib.request.Request(self.base + "/api/chat", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    def warm_up(self, model: str) -> None:
        """Load the model into memory ahead of the first question (cold load costs ~5-10 s on CPU)."""
        body = {"model": model, "messages": [], "stream": False}
        if self.keep_alive:
            body["keep_alive"] = self.keep_alive
        self._post(body, timeout=120)

    def complete_json(self, model, system, user, schema, temperature=0.2, max_tokens=2000, timeout=None) -> str:
        wait = min(self.timeout, timeout) if timeout else self.timeout
        body = {"model": model, "stream": False, "format": schema,
                "options": {"temperature": temperature, "num_predict": max_tokens,
                            **({"num_ctx": self.num_ctx} if self.num_ctx else {})},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if self.think is not None:
            body["think"] = self.think
        if self.keep_alive:
            body["keep_alive"] = self.keep_alive
        for attempt in range(2):
            try:
                return self._post(body, wait)["message"]["content"]
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="ignore")
                if attempt == 0 and "think" in body and "think" in detail.lower():
                    body.pop("think")  # model without thinking support
                    continue
                if e.code == 404:
                    raise ProviderUnavailable(f"ollama: model {model!r} not found ({detail[:120]})") from e
                raise LLMError(f"ollama HTTP {e.code}: {detail[:200]}") from e
            except TimeoutError as e:  # closing the socket also stops Ollama generating
                raise LLMTimeout(f"ollama: no answer within {wait:.0f} s") from e
            except urllib.error.URLError as e:
                if isinstance(e.reason, TimeoutError):
                    raise LLMTimeout(f"ollama: no answer within {wait:.0f} s") from e
                raise ProviderUnavailable(f"ollama unreachable at {self.base}: {e}") from e
            except ConnectionError as e:
                raise ProviderUnavailable(f"ollama unreachable at {self.base}: {e}") from e
        raise LLMError("unreachable")
