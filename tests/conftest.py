"""Shared pytest fixtures.

Every test runs against a fresh temporary vault directory and a fixed master
key supplied via VIBE_SECRETS_MASTER. The OS keychain is never touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet


@pytest.fixture()
def vault_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VIBE_SECRETS_HOME", str(tmp_path))
    monkeypatch.setenv("VIBE_SECRETS_MASTER", Fernet.generate_key().decode("ascii"))
    monkeypatch.delenv("VIBE_SECRETS_ACTOR", raising=False)
    return tmp_path
