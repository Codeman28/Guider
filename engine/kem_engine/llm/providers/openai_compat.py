"""OpenAI-compatible cloud providers (OpenRouter; Gemini via its OpenAI-compat endpoint — TODO(verify)).

Only ever receives sanitized payloads (the client enforces this for every non-local provider).
"""
from __future__ import annotations

from ..config import ProviderConf
from .base import LLMError, LLMTimeout, ProviderUnavailable, QuotaExceeded


class OpenAICompatProvider:
    is_local = False
    supports_json_schema = True

    def __init__(self, conf: ProviderConf):
        self.name = conf.name
        self.conf = conf
        self._client = None

    def _c(self):
        if self._client is None:
            key = self.conf.api_key()
            if not key:
                raise ProviderUnavailable(f"{self.name}: env {self.conf.api_key_env} is not set")
            from openai import OpenAI
            self._client = OpenAI(base_url=self.conf.base_url, api_key=key, timeout=self.conf.timeout_s)
        return self._client

    def complete_json(self, model, system, user, schema, temperature=0.2, max_tokens=2000, timeout=None) -> str:
        import openai
        try:
            r = self._c().chat.completions.create(
                model=model, temperature=temperature, max_tokens=max_tokens, timeout=timeout or self.conf.timeout_s,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={"type": "json_schema", "json_schema": {"name": "out", "schema": schema}})
        except openai.APITimeoutError as e:
            raise LLMTimeout(f"{self.name}: {e}") from e
        except openai.RateLimitError as e:  # OpenRouter: 429 + X-RateLimit-* headers
            raise QuotaExceeded(f"{self.name}: {e}") from e
        except (openai.APIConnectionError, openai.AuthenticationError, openai.NotFoundError) as e:
            raise ProviderUnavailable(f"{self.name}: {e}") from e
        except openai.APIError as e:
            raise LLMError(f"{self.name}: {e}") from e
        return r.choices[0].message.content or ""
