from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from vibe_secrets.vault import Vault, VaultError


def test_reset_master_re_encrypts_with_new_key(
    tmp_path: Path, vault_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    v = Vault()
    v.init_empty()
    v.add("ANTHROPIC_API_KEY", "global", "the-only-secret")
    before_ct = v.path.read_bytes()

    # Simulate the keychain by flipping VIBE_SECRETS_MASTER in-step with the rotation.
    # The vault uses `replace_master`, which is a no-op under VIBE_SECRETS_MASTER; we
    # call reset_master and verify the on-disk ciphertext changes and records survive.
    result = v.reset_master()

    assert result["records"] == 1
    after_ct = v.path.read_bytes()
    assert after_ct != before_ct
    assert b"the-only-secret" not in after_ct

    # Under env-override mode, the master env var is the keyring — it wasn't
    # rotated automatically. To verify the rotated key really encrypts the
    # vault, we need to use the key the vault now holds in-memory.
    # Get it via a fresh decrypt roundtrip: write to monkeypatched env, reload.
    # Simplest check: re-read via the existing Vault instance (still has new fernet).
    assert v.get("ANTHROPIC_API_KEY", "global").value == "the-only-secret"

    # A brand-new Vault() instance using the OLD master env should FAIL:
    v2 = Vault()
    with pytest.raises(VaultError):
        v2.list()


def test_reset_master_preserves_all_records(tmp_path: Path, vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    v.add("KEY_A", "global", "aa")
    v.add("KEY_B", "global", "bb")
    v.add("KEY_C", "project:demo:dev", "cc")
    v.reset_master()
    assert v.get("KEY_A", "global").value == "aa"
    assert v.get("KEY_B", "global").value == "bb"
    assert v.get("KEY_C", "project:demo:dev").value == "cc"


def test_reset_master_writes_pre_reset_backup(tmp_path: Path, vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    v.add("KEY_A", "global", "v")
    result = v.reset_master()
    backup_path = Path(result["backup"])
    assert backup_path.exists()
    # The backup is the old ciphertext — non-empty, opaque bytes.
    assert len(backup_path.read_bytes()) > 0


def test_reset_master_fails_loudly_on_wrong_current_master(
    tmp_path: Path, vault_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    v = Vault()
    v.init_empty()
    v.add("KEY_A", "global", "v")
    # Now swap the env-override master so the current vault can't be decrypted.
    monkeypatch.setenv("VIBE_SECRETS_MASTER", Fernet.generate_key().decode("ascii"))
    v2 = Vault()
    with pytest.raises(VaultError):
        v2.reset_master()
