"""Load config/llm.toml (SPEC §7.2)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "llm.toml"


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

    @property
    def is_local(self) -> bool:
        return self.name == "ollama"

    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env) if self.api_key_env else None


@dataclass
class LLMConfig:
    provider: str
    planner_model: str
    writer_model: str
    grounder_model: str
    fallback: list[str]
    providers: dict[str, ProviderConf]
    max_calls: int

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
                                               o.get("timeout_s", 120))
        return cls(provider=d.get("provider", "ollama"), planner_model=d.get("planner_model", ""),
                   writer_model=d.get("writer_model", ""), grounder_model=d.get("grounder_model", ""),
                   fallback=list(d.get("fallback", [])), providers=providers,
                   max_calls=int(raw.get("budget", {}).get("max_llm_calls_per_tutorial", 3)))
