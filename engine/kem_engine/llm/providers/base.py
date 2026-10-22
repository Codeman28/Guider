"""Provider interface (SPEC §7.1). Synchronous: the engine runs a session on one worker thread."""
from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)


class LLMError(Exception):
    pass


class QuotaExceeded(LLMError):
    """429 / platform rate limit — the router moves on to the next provider."""


class ProviderUnavailable(LLMError):
    """Connection refused, model missing, no API key."""


class LLMProvider(Protocol):
    name: str
    is_local: bool
    supports_json_schema: bool

    def complete_json(self, model: str, system: str, user: str, schema: dict,
                      temperature: float = 0.2, max_tokens: int = 2000) -> str:
        """Return the raw JSON text. Validation and repair happen in the caller (pydantic)."""
        ...
