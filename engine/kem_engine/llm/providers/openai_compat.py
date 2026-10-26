"""OpenAI-compatible cloud providers (OpenRouter; Gemini via its OpenAI-compat endpoint, checked 25/10/2026).

Only ever receives sanitized payloads (the client enforces this for every non-local provider).
"""
from __future__ import annotations

import json

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
                raise ProviderUnavailable(f"{self.name}: chưa có API key (nhập trong Cài đặt của Guider)")
            from openai import OpenAI
            # no silent SDK retries: a stuck model must fail fast so the caller can fall back (25/10/2026)
            self._client = OpenAI(base_url=self.conf.base_url, api_key=key, timeout=self.conf.timeout_s, max_retries=0)
        return self._client

    def complete_json(self, model, system, user, schema, temperature=0.2, max_tokens=2000, timeout=None) -> str:
        import openai
        extra = {"reasoning_effort": self.conf.reasoning_effort} if self.conf.reasoning_effort else {}
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        try:
            try:
                r = self._c().chat.completions.create(
                    model=model, temperature=temperature, max_tokens=max_tokens,
                    timeout=timeout or self.conf.timeout_s, messages=messages, **extra,
                    response_format={"type": "json_schema", "json_schema": {"name": "out", "schema": schema}})
            except openai.BadRequestError:
                # Some endpoints reject parts of a pydantic JSON Schema ($defs, enums…): ask for plain JSON
                # with the schema in the prompt; the client still validates the result with pydantic.
                messages[0] = {"role": "system", "content": system + " JSON schema bắt buộc: "
                               + json.dumps(schema, ensure_ascii=False)}
                r = self._c().chat.completions.create(
                    model=model, temperature=temperature, max_tokens=max_tokens,
                    timeout=timeout or self.conf.timeout_s, messages=messages, **extra,
                    response_format={"type": "json_object"})
        except openai.APITimeoutError as e:
            raise LLMTimeout(f"{self.name}: {e}") from e
        except openai.RateLimitError as e:  # OpenRouter: 429 + X-RateLimit-* headers
            raise QuotaExceeded(f"{self.name}: {e}") from e
        except (openai.APIConnectionError, openai.AuthenticationError, openai.NotFoundError) as e:
            raise ProviderUnavailable(f"{self.name}: {e}") from e
        except openai.APIError as e:
            raise LLMError(f"{self.name}: {e}") from e
        return r.choices[0].message.content or ""
