from __future__ import annotations

from pathlib import Path

import pytest

from vibe_secrets import backup as backup_mod
from vibe_secrets import registry
from vibe_secrets.vault import Vault


def _populate(vault: Vault, tmp_path: Path) -> None:
    vault.add("ANTHROPIC_API_KEY", "global", "sk-original-1")
    vault.add("SUPABASE_URL", "project:demo:dev", "https://a.supabase.co")
    p = tmp_path / "demo"
    p.mkdir()
    registry.register(p, "demo", "dev")
    registry.record_inject(p, "demo", "dev", ["ANTHROPIC_API_KEY", "SUPABASE_URL"])


def test_backup_round_trip_replace(tmp_path: Path, vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    _populate(v, tmp_path)
    bfile = tmp_path / "vault.vsb"
    backup_mod.write_backup(bfile, "correct horse battery staple")

    # Wipe local state.
    v.path.unlink()
    registry.save({"version": 1, "projects": {}})
    v2 = Vault()
    v2.init_empty()
    assert v2.list() == []
    assert registry.list_all() == []

    summary = backup_mod.restore_from_backup(bfile, "correct horse battery staple", mode="replace")
    assert summary["mode"] == "replace"
    assert summary["records"] == 2

    v3 = Vault()
    assert {r.name for r in v3.list()} == {"ANTHROPIC_API_KEY", "SUPABASE_URL"}
    assert v3.get("ANTHROPIC_API_KEY", "global").value == "sk-original-1"
    assert any(p["name"] == "demo" for p in registry.list_all())


def test_backup_wrong_passphrase_rejected(tmp_path: Path, vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    v.add("KEY_A", "global", "v")
    bfile = tmp_path / "vault.vsb"
    backup_mod.write_backup(bfile, "right-passphrase")
    with pytest.raises(backup_mod.BackupError):
        backup_mod.read_backup(bfile, "WRONG-passphrase")


def test_backup_tampered_file_rejected(tmp_path: Path, vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    v.add("KEY_A", "global", "v")
    bfile = tmp_path / "vault.vsb"
    backup_mod.write_backup(bfile, "pass")
    data = bytearray(bfile.read_bytes())
    data[-1] ^= 0xFF
    bfile.write_bytes(bytes(data))
    with pytest.raises(backup_mod.BackupError):
        backup_mod.read_backup(bfile, "pass")


def test_backup_rejects_non_backup_file(tmp_path: Path, vault_env: Path) -> None:
    bogus = tmp_path / "not-a-backup"
    bogus.write_bytes(b"hello world")
    with pytest.raises(backup_mod.BackupError):
        backup_mod.read_backup(bogus, "anything")


def test_backup_is_portable_across_master_keys(
    tmp_path: Path, vault_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate moving a backup to a new machine: change the OS keychain
    master and ensure we can still restore with the passphrase."""
    v = Vault()
    v.init_empty()
    v.add("KEY_A", "global", "original-value")
    bfile = tmp_path / "vault.vsb"
    backup_mod.write_backup(bfile, "portable-pass")

    # Simulate a new machine: different master key, empty vault dir.
    from cryptography.fernet import Fernet

    new_master = Fernet.generate_key().decode("ascii")
    monkeypatch.setenv("VIBE_SECRETS_MASTER", new_master)
    new_home = tmp_path / "new-machine"
    monkeypatch.setenv("VIBE_SECRETS_HOME", str(new_home))

    summary = backup_mod.restore_from_backup(bfile, "portable-pass", mode="replace")
    assert summary["records"] == 1
    v2 = Vault()
    assert v2.get("KEY_A", "global").value == "original-value"


def test_merge_adds_only_missing(tmp_path: Path, vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    v.add("SHARED_KEY", "global", "local-value")
    v.add("LOCAL_ONLY", "global", "kept")
    bfile = tmp_path / "vault.vsb"

    # Create a backup from a separate state: different SHARED_KEY value + an extra key.
    v2_home = tmp_path / "other"
    import os as _os

    _os.environ["VIBE_SECRETS_HOME"] = str(v2_home)  # shift the vault temporarily
    v_other = Vault()
    v_other.init_empty()
    v_other.add("SHARED_KEY", "global", "other-value")
    v_other.add("BACKUP_ONLY", "global", "from-backup")
    backup_mod.write_backup(bfile, "pass")

    # Switch back to original home.
    _os.environ["VIBE_SECRETS_HOME"] = str(vault_env)

    summary = backup_mod.restore_from_backup(bfile, "pass", mode="merge")
    assert summary["mode"] == "merge"
    assert summary["records_added"] == 1
    assert summary["records_skipped"] == 1

    v3 = Vault()
    assert v3.get("SHARED_KEY", "global").value == "local-value"  # preserved
    assert v3.get("LOCAL_ONLY", "global").value == "kept"
    assert v3.get("BACKUP_ONLY", "global").value == "from-backup"


def test_empty_passphrase_rejected(tmp_path: Path, vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    v.add("KEY_A", "global", "v")
    with pytest.raises(backup_mod.BackupError):
        backup_mod.write_backup(tmp_path / "x.vsb", "")
