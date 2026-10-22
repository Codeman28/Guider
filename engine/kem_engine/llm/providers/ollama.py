"""Ollama native /api/chat with `format` = JSON schema (structured outputs; S7: 100% schema-valid)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from ..config import ProviderConf
from .base import LLMError, ProviderUnavailable


class OllamaProvider:
    name = "ollama"
    is_local = True
    supports_json_schema = True

    def __init__(self, conf: ProviderConf):
        self.base = conf.base_url.rstrip("/")
        self.timeout = conf.timeout_s
        self.think = conf.think
        self.keep_alive = conf.keep_alive

    def _post(self, body: dict) -> dict:
        req = urllib.request.Request(self.base + "/api/chat", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())

    def complete_json(self, model, system, user, schema, temperature=0.2, max_tokens=2000) -> str:
        body = {"model": model, "stream": False, "format": schema,
                "options": {"temperature": temperature, "num_predict": max_tokens},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if self.think is not None:
            body["think"] = self.think
        if self.keep_alive:
            body["keep_alive"] = self.keep_alive
        for attempt in range(2):
            try:
                return self._post(body)["message"]["content"]
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="ignore")
                if attempt == 0 and "think" in body and "think" in detail.lower():
                    body.pop("think")  # model without thinking support
                    continue
                if e.code == 404:
                    raise ProviderUnavailable(f"ollama: model {model!r} not found ({detail[:120]})") from e
                raise LLMError(f"ollama HTTP {e.code}: {detail[:200]}") from e
            except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
                raise ProviderUnavailable(f"ollama unreachable at {self.base}: {e}") from e
        raise LLMError("unreachable")
