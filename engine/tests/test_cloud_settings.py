"""ADR-0003: Gemini key storage (DPAPI) and the app's provider choice."""
import json

from kem_engine.llm import secrets
from kem_engine.llm.config import LLMConfig


def test_dpapi_roundtrip_and_remove(tmp_path):
    p = tmp_path / "secrets.bin"
    assert secrets.get_key("gemini", p) is None
    secrets.set_key("gemini", "  AIza-test-key  ", p)
    assert b"AIza" not in p.read_bytes()  # encrypted at rest
    assert secrets.get_key("gemini", p) == "AIza-test-key"
    secrets.set_key("gemini", None, p)
    assert not secrets.has_key("gemini", p)


def test_corrupt_secrets_file_means_no_key(tmp_path):
    p = tmp_path / "secrets.bin"
    p.write_bytes(b"not dpapi")
    assert secrets.get_key("gemini", p) is None


def test_app_choice_enables_gemini_with_ollama_fallback(tmp_path, monkeypatch):
    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"provider": "gemini"}), encoding="utf-8")
    monkeypatch.setenv("KEM_SETTINGS", str(s))
    cfg = LLMConfig.load()
    assert cfg.provider == "gemini" and cfg.providers["gemini"].enabled
    assert cfg.fallback[-1] == "ollama"
    assert cfg.providers["gemini"].models == ["gemini-3.5-flash-lite"]
    assert cfg.providers["gemini"].reasoning_effort == "low"


def test_default_stays_local():
    cfg = LLMConfig.load()
    assert cfg.provider == "ollama" and not cfg.providers["gemini"].enabled
