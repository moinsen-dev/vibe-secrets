"""Encrypted, portable backup and restore.

A backup file is a self-contained archive encrypted with a user-supplied
passphrase. It can be safely moved between machines — it is NOT tied to
the OS keychain of the machine that produced it.

File format:
  bytes   0..7   magic       b"VSBACKUP"
  byte       8   version     1
  bytes   9..24  salt        16 random bytes (for PBKDF2)
  bytes  25..   ciphertext   Fernet token (base64, ASCII) of payload

Payload (plaintext):
  {
    "version": 1,
    "created_at": "<iso>",
    "vault_records": { "<scope>/<name>": {…}, … },   # values included
    "registry":      { "version": 1, "projects": {…} }
  }

PBKDF2 params: HMAC-SHA256, 600_000 iterations, 32-byte key → url-safe b64
"""

from __future__ import annotations

import base64
import dataclasses
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from . import registry
from .models import KeyRecord
from .vault import Vault, VaultError

MAGIC = b"VSBACKUP"
BACKUP_VERSION = 1
SALT_LEN = 16
KDF_ITERATIONS = 600_000
KDF_KEY_LEN = 32


class BackupError(Exception):
    pass


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=KDF_KEY_LEN,
        salt=salt,
        iterations=KDF_ITERATIONS,
    )
    raw = kdf.derive(passphrase.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


def write_backup(
    path: Path | str,
    passphrase: str,
    vault: Vault | None = None,
) -> dict:
    if not passphrase:
        raise BackupError("Passphrase must not be empty.")
    v = vault or Vault()
    v._load()
    records_public = {rid: dataclasses.asdict(rec) for rid, rec in v._records.items()}
    payload = {
        "version": BACKUP_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "vault_records": records_public,
        "registry": registry.load(),
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    salt = os.urandom(SALT_LEN)
    fernet = Fernet(_derive_key(passphrase, salt))
    ciphertext = fernet.encrypt(raw)

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    header = MAGIC + bytes([BACKUP_VERSION]) + salt
    out.write_bytes(header + ciphertext)
    try:
        os.chmod(out, 0o600)
    except OSError:
        pass
    return {
        "path": str(out),
        "records": len(records_public),
        "projects": len(payload["registry"].get("projects", {})),
        "created_at": payload["created_at"],
    }


def read_backup(
    path: Path | str,
    passphrase: str,
) -> dict:
    src = Path(path)
    if not src.exists():
        raise BackupError(f"Backup file not found: {src}")
    data = src.read_bytes()
    if len(data) < len(MAGIC) + 1 + SALT_LEN + 1:
        raise BackupError("Backup file is too short or corrupt.")
    if not data.startswith(MAGIC):
        raise BackupError("Not a vibe-secrets backup (magic header missing).")
    version = data[len(MAGIC)]
    if version != BACKUP_VERSION:
        raise BackupError(f"Unsupported backup version {version}. Expected {BACKUP_VERSION}.")
    salt_start = len(MAGIC) + 1
    salt = data[salt_start : salt_start + SALT_LEN]
    ciphertext = data[salt_start + SALT_LEN :]
    try:
        plaintext = Fernet(_derive_key(passphrase, salt)).decrypt(ciphertext)
    except InvalidToken as e:
        raise BackupError("Bad passphrase or corrupted backup.") from e
    try:
        return json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise BackupError("Backup payload is not valid JSON.") from e


def restore_from_backup(
    path: Path | str,
    passphrase: str,
    mode: str = "replace",
    vault: Vault | None = None,
) -> dict:
    """Restore a backup onto the current vault + registry.

    mode:
      * "replace" — existing vault records and registry are REPLACED with backup's.
      * "merge"   — backup entries are added; existing entries are preserved on conflict.
    """
    if mode not in ("replace", "merge"):
        raise BackupError(f"Invalid mode {mode!r}. Use 'replace' or 'merge'.")

    payload = read_backup(path, passphrase)

    v = vault or Vault()
    records_in = payload.get("vault_records", {}) or {}
    registry_in = payload.get("registry", {"version": 1, "projects": {}})

    # Load current state (if any). If vault file doesn't exist, create empty.
    if not v.exists():
        v.init_empty()
    else:
        try:
            v._load()
        except VaultError:
            # Master mismatch — we'll overwrite anyway if mode=replace.
            if mode == "merge":
                raise

    if mode == "replace":
        v._records = {rid: KeyRecord.from_storage(data) for rid, data in records_in.items()}
        v._save()
        registry.save(
            registry_in if isinstance(registry_in, dict) else {"version": 1, "projects": {}}
        )
        return {
            "mode": "replace",
            "records": len(records_in),
            "projects": len(registry_in.get("projects", {})),
        }

    # merge
    merged_added = 0
    merged_skipped = 0
    for rid, data in records_in.items():
        if rid in v._records:
            merged_skipped += 1
            continue
        v._records[rid] = KeyRecord.from_storage(data)
        merged_added += 1
    v._save()

    reg_now = registry.load()
    projects_in = (registry_in.get("projects") or {}) if isinstance(registry_in, dict) else {}
    proj_added = 0
    proj_skipped = 0
    for path_key, entry in projects_in.items():
        if path_key in reg_now["projects"]:
            proj_skipped += 1
            continue
        reg_now["projects"][path_key] = entry
        proj_added += 1
    registry.save(reg_now)

    return {
        "mode": "merge",
        "records_added": merged_added,
        "records_skipped": merged_skipped,
        "projects_added": proj_added,
        "projects_skipped": proj_skipped,
    }
