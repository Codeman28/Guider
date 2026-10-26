"""Load config/llm.toml (SPEC §7.2)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "llm.toml"


def settings_path() -> Path:
    """User choices from the app (settings.set): %LOCALAPPDATA%/Kem/settings.json."""
    if os.environ.get("KEM_SETTINGS"):
        return Path(os.environ["KEM_SETTINGS"])
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Kem" / "settings.json"


@dataclass
class ProviderConf:
    name: str
    enabled: bool
    base_url: str
    models: list[str] = field(default_factory=list)
    api_key_env: str | None = None
    timeout_s: float = 120.0
    think: bool | None = None
    keep_alive: str | None = None
    reasoning_effort: str | None = None  # OpenAI-compat providers that think (Gemini 3: lowest is "low")
    num_ctx: int | None = None  # Ollama context window; its default (4096) is smaller than a training call

    @property
    def is_local(self) -> bool:
        return self.name == "ollama"

    def api_key(self) -> str | None:
        """Environment variable first (developer use), then the key the user saved in the app (DPAPI)."""
        if self.api_key_env and os.environ.get(self.api_key_env):
            return os.environ[self.api_key_env]
        from .secrets import get_key
        return get_key(self.name)


@dataclass
class LLMConfig:
    provider: str
    planner_model: str
    writer_model: str
    grounder_model: str
    fallback: list[str]
    providers: dict[str, ProviderConf]
    max_calls: int
    max_seconds: float = 110.0
    planner_reserve_s: float = 60.0

    @classmethod
    def load(cls, path: Path | None = None) -> "LLMConfig":
        path = path or Path(os.environ.get("KEM_LLM_CONFIG", DEFAULT_PATH))
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        d = raw.get("default", {})
        providers: dict[str, ProviderConf] = {}
        if "ollama" in raw:
            o = raw["ollama"]
            providers["ollama"] = ProviderConf("ollama", o.get("enabled", True), o["base_url"],
                                               timeout_s=o.get("timeout_s", 600), think=o.get("think"),
                                               keep_alive=o.get("keep_alive"))
        if "openrouter" in raw:
            o = raw["openrouter"]
            providers["openrouter"] = ProviderConf("openrouter", o.get("enabled", False), o["base_url"],
                                                   list(o.get("models", [])), o.get("api_key_env"),
                                                   o.get("timeout_s", 120))
        if "gemini" in raw:
            o = raw["gemini"]
            providers["gemini"] = ProviderConf("gemini", o.get("enabled", False), o["base_url"],
                                               [o["model"]] if o.get("model") else [], o.get("api_key_env"),
                                               o.get("timeout_s", 120), reasoning_effort=o.get("reasoning_effort"))
        provider, fallback = d.get("provider", "ollama"), list(d.get("fallback", []))
        chosen = _user_provider()
        if chosen and chosen in providers:  # the app's choice wins; the local model always stays as fallback
            providers[chosen].enabled = True
            provider = chosen
            if chosen != "ollama" and "ollama" in providers:
                fallback = [f for f in fallback if f != "ollama"] + ["ollama"]
        return cls(provider=provider, planner_model=d.get("planner_model", ""),
                   writer_model=d.get("writer_model", ""), grounder_model=d.get("grounder_model", ""),
                   fallback=fallback, providers=providers,
                   max_calls=int(raw.get("budget", {}).get("max_llm_calls_per_tutorial", 3)),
                   max_seconds=float(raw.get("budget", {}).get("max_seconds_per_tutorial", 110)),
                   planner_reserve_s=float(raw.get("budget", {}).get("planner_reserve_s", 60)))


def _user_provider() -> str | None:
    import json
    try:
        return json.loads(settings_path().read_text(encoding="utf-8")).get("provider") or None
    except (OSError, ValueError):
        return None
