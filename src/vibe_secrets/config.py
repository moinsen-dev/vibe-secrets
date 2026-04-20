"""Runtime paths for the vault. All read from env vars so tests can redirect them."""

from __future__ import annotations

import os
from pathlib import Path


def vault_dir() -> Path:
    return Path(os.environ.get("VIBE_SECRETS_HOME", str(Path.home() / ".vibe-secrets")))


def vault_file() -> Path:
    return vault_dir() / "vault.enc"


def audit_file() -> Path:
    return vault_dir() / "audit.log"


def ensure_vault_dir() -> Path:
    d = vault_dir()
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d
