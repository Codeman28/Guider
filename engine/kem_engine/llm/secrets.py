"""API keys for optional cloud providers (ADR-0003). Encrypted with Windows DPAPI (bound to the Windows
user account) in %LOCALAPPDATA%\\Kem\\secrets.bin. Keys never go to settings.json, logs, traces or RPC
results."""
from __future__ import annotations

import json
import os
from pathlib import Path

ENTROPY = b"Guider.secrets.v1"


def secrets_path() -> Path:
    if os.environ.get("KEM_SECRETS"):
        return Path(os.environ["KEM_SECRETS"])
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Kem" / "secrets.bin"


def _load(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    import win32crypt
    try:
        _, raw = win32crypt.CryptUnprotectData(path.read_bytes(), ENTROPY, None, None, 0)
        return json.loads(raw.decode("utf-8"))
    except Exception:  # another user's file or corrupted: behave as if no key was saved
        return {}


def get_key(provider: str, path: Path | None = None) -> str | None:
    return _load(path or secrets_path()).get(provider) or None


def set_key(provider: str, key: str | None, path: Path | None = None) -> None:
    """key=None (or empty) removes the provider's key."""
    import win32crypt
    path = path or secrets_path()
    data = _load(path)
    if key and key.strip():
        data[provider] = key.strip()
    else:
        data.pop(provider, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = win32crypt.CryptProtectData(json.dumps(data).encode("utf-8"), "Guider", ENTROPY, None, None, 0)
    path.write_bytes(blob)


def has_key(provider: str, path: Path | None = None) -> bool:
    return get_key(provider, path) is not None
