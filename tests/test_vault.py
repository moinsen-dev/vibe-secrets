from __future__ import annotations

from pathlib import Path

import pytest

from vibe_secrets.vault import AlreadyExists, NotFound, Vault, VaultError


def test_init_and_round_trip(vault_env: Path) -> None:
    v = Vault()
    assert not v.exists()
    v.init_empty()
    assert v.exists()
    assert v.list() == []


def test_add_get_list(vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    v.add("ANTHROPIC_API_KEY", "global", "sk-secret-1")
    v.add("OPENAI_API_KEY", "global", "sk-secret-2")
    v.add("SUPABASE_URL", "project:saleson:dev", "https://example.supabase.co")

    rec = v.get("ANTHROPIC_API_KEY", "global")
    assert rec.value == "sk-secret-1"
    assert rec.status == "active"

    all_records = v.list()
    assert len(all_records) == 3
    globals_only = v.list("global")
    assert {r.name for r in globals_only} == {"ANTHROPIC_API_KEY", "OPENAI_API_KEY"}


def test_duplicate_add_rejected(vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    v.add("A_KEY", "global", "v1")
    with pytest.raises(AlreadyExists):
        v.add("A_KEY", "global", "v2")


def test_rotate_replaces_value_and_marks_previous(vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    v.add("TEST_KEY", "global", "old")
    new = v.rotate("TEST_KEY", "global", "brand-new")
    assert new.value == "brand-new"
    assert new.rotated_from is not None
    assert v.get("TEST_KEY", "global").value == "brand-new"


def test_revoke_keeps_record_marks_revoked(vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    v.add("TEST_KEY", "global", "old")
    v.revoke("TEST_KEY", "global")
    assert v.get("TEST_KEY", "global").status == "revoked"


def test_delete_is_hard(vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    v.add("TEST_KEY", "global", "x")
    v.delete("TEST_KEY", "global")
    with pytest.raises(NotFound):
        v.get("TEST_KEY", "global")


def test_search_glob_and_substring(vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    v.add("SUPABASE_URL", "global", "x")
    v.add("SUPABASE_KEY", "global", "y")
    v.add("ANTHROPIC_API_KEY", "global", "z")
    got = {r.name for r in v.search("SUPABASE_*")}
    assert got == {"SUPABASE_URL", "SUPABASE_KEY"}
    got2 = {r.name for r in v.search("API")}
    assert "ANTHROPIC_API_KEY" in got2


def test_encryption_at_rest(vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    v.add("ANTHROPIC_API_KEY", "global", "super-secret-value")
    raw = v.path.read_bytes()
    assert b"super-secret-value" not in raw
    assert b"ANTHROPIC_API_KEY" not in raw


def test_tamper_detection(vault_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    v = Vault()
    v.init_empty()
    v.add("TEST_KEY", "global", "v")
    # Corrupt the ciphertext.
    data = bytearray(v.path.read_bytes())
    data[-1] ^= 0xFF
    v.path.write_bytes(bytes(data))
    # A new vault instance re-reads and must reject tampering.
    v2 = Vault()
    with pytest.raises(VaultError):
        v2.list()


def test_wrong_master_rejected(vault_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    v = Vault()
    v.init_empty()
    v.add("TEST_KEY", "global", "v")
    # Swap master. Vault is loaded lazily — use a fresh instance.
    from cryptography.fernet import Fernet

    monkeypatch.setenv("VIBE_SECRETS_MASTER", Fernet.generate_key().decode("ascii"))
    v2 = Vault()
    with pytest.raises(VaultError):
        v2.list()


def test_invalid_name_rejected(vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    with pytest.raises(ValueError):
        v.add("lowercase_name", "global", "x")


def test_invalid_scope_rejected(vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    with pytest.raises(ValueError):
        v.add("GOOD_NAME", "project:missing-parts", "x")


def test_stats(vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    v.add("KEY_AA", "global", "1")
    v.add("KEY_BB", "global", "2")
    v.add("KEY_CC", "project:p:dev", "3")
    v.revoke("KEY_AA", "global")
    s = v.stats()
    assert s["total"] == 3
    assert s["active"] == 2
    assert s["revoked"] == 1
    assert s["scopes"] == {"global": 2, "project:p:dev": 1}
