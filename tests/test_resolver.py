from __future__ import annotations

from pathlib import Path

from vibe_secrets.resolver import resolve
from vibe_secrets.vault import Vault


def test_project_overrides_global(vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    v.add("ANTHROPIC_API_KEY", "global", "global-key")
    v.add("ANTHROPIC_API_KEY", "project:saleson:dev", "project-key")
    out = resolve(v, ["ANTHROPIC_API_KEY"], "saleson", "dev")
    assert len(out) == 1
    r = out[0]
    assert r.source == "project"
    assert r.record is not None
    assert r.record.value == "project-key"


def test_falls_back_to_global(vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    v.add("OPENAI_API_KEY", "global", "g-val")
    out = resolve(v, ["OPENAI_API_KEY"], "saleson", "dev")
    assert out[0].source == "global"
    assert out[0].record is not None
    assert out[0].record.value == "g-val"


def test_missing_reports_missing(vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    out = resolve(v, ["GHOST_KEY"], "saleson", "dev")
    assert out[0].source == "missing"
    assert out[0].record is None


def test_revoked_global_not_returned(vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    v.add("TEST_KEY", "global", "v")
    v.revoke("TEST_KEY", "global")
    out = resolve(v, ["TEST_KEY"], "saleson", "dev")
    assert out[0].source == "revoked"
    assert out[0].record is None


def test_revoked_project_blocks_fallback(vault_env: Path) -> None:
    """If the project scope has a revoked record we must not silently fall through
    to the global scope — the user's intent was clearly to override."""
    v = Vault()
    v.init_empty()
    v.add("TEST_KEY", "global", "global-value")
    v.add("TEST_KEY", "project:saleson:dev", "p-val")
    v.revoke("TEST_KEY", "project:saleson:dev")
    out = resolve(v, ["TEST_KEY"], "saleson", "dev")
    assert out[0].source == "revoked"
    assert out[0].record is None


def test_no_project_resolves_to_global_only(vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    v.add("TEST_KEY", "global", "v")
    out = resolve(v, ["TEST_KEY"], None, None)
    assert out[0].source == "global"
    assert out[0].record is not None
