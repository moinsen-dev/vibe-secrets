"""Core vault: encrypted, scoped store of KeyRecords.

Storage layout (inside the encrypted blob):

    {
      "version": 1,
      "records": {
        "<scope>/<name>": { ...KeyRecord... },
        ...
      }
    }

The encrypted blob is written atomically with 0o600 permissions.
"""

from __future__ import annotations

import fnmatch
import json
import os
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .config import ensure_vault_dir, vault_file
from .keystore import load_master
from .models import (
    KeyRecord,
    now_iso,
    validate_name,
    validate_scope,
)

VAULT_FORMAT_VERSION = 1


class VaultError(Exception):
    pass


class VaultNotInitialized(VaultError):
    pass


class NotFound(VaultError):
    pass


class AlreadyExists(VaultError):
    pass


class Vault:
    def __init__(self, path: Path | None = None):
        self._path = path or vault_file()
        self._records: dict[str, KeyRecord] = {}
        self._loaded = False
        self._fernet: Fernet | None = None

    # ---------- lifecycle ----------

    @property
    def path(self) -> Path:
        return self._path

    def _cipher(self) -> Fernet:
        if self._fernet is None:
            self._fernet = Fernet(load_master())
        return self._fernet

    def exists(self) -> bool:
        return self._path.exists()

    def init_empty(self) -> None:
        if self.exists():
            raise VaultError(f"Vault already exists at {self._path}")
        self._records = {}
        self._loaded = True
        self._save()

    def _require_initialized(self) -> None:
        if not self.exists():
            raise VaultNotInitialized(f"No vault at {self._path}. Run `vibe-secrets init` first.")

    def _load(self) -> None:
        if self._loaded:
            return
        if not self._path.exists():
            self._records = {}
            self._loaded = True
            return
        raw = self._path.read_bytes()
        try:
            plain = self._cipher().decrypt(raw)
        except InvalidToken as e:
            raise VaultError(
                "Vault decryption failed. The master key in the OS keychain "
                "does not match this vault file."
            ) from e
        try:
            payload = json.loads(plain.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise VaultError(f"Vault is corrupted: {e}") from e
        version = payload.get("version", 1)
        if version != VAULT_FORMAT_VERSION:
            raise VaultError(
                f"Unsupported vault format version {version}. Expected {VAULT_FORMAT_VERSION}."
            )
        records = payload.get("records", {}) or {}
        self._records = {rid: KeyRecord.from_storage(data) for rid, data in records.items()}
        self._loaded = True

    def _save(self) -> None:
        payload = {
            "version": VAULT_FORMAT_VERSION,
            "records": {rid: r.to_storage() for rid, r in self._records.items()},
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        enc = self._cipher().encrypt(raw)
        ensure_vault_dir()
        # Atomic write, same directory so os.replace is cross-device safe.
        directory = self._path.parent
        fd, tmp_path = tempfile.mkstemp(prefix=".vault.", suffix=".tmp", dir=str(directory))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(enc)
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, self._path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass

    # ---------- queries ----------

    def list(self, scope: str | None = None) -> list[KeyRecord]:
        self._load()
        vals = self._records.values()
        if scope is not None:
            vals = [r for r in vals if r.scope == scope]
        return sorted(vals, key=lambda r: (r.scope, r.name))

    def list_scopes(self) -> list[str]:
        self._load()
        return sorted({r.scope for r in self._records.values()})

    def search(self, pattern: str) -> list[KeyRecord]:
        self._load()
        pat = pattern.upper()
        results: list[KeyRecord] = []
        for r in self._records.values():
            name_up = r.name.upper()
            if fnmatch.fnmatchcase(name_up, pat) or pat in name_up:
                results.append(r)
        return sorted(results, key=lambda r: (r.scope, r.name))

    def try_get(self, name: str, scope: str) -> KeyRecord | None:
        self._load()
        return self._records.get(f"{scope}/{name}")

    def get(self, name: str, scope: str) -> KeyRecord:
        rec = self.try_get(name, scope)
        if rec is None:
            raise NotFound(f"{scope}/{name}")
        return rec

    # ---------- mutations ----------

    def add(self, name: str, scope: str, value: str) -> KeyRecord:
        validate_name(name)
        validate_scope(scope)
        self._load()
        rid = f"{scope}/{name}"
        existing = self._records.get(rid)
        if existing and existing.status == "active":
            raise AlreadyExists(f"{rid} already exists. Use `rotate` to replace the value.")
        rec = KeyRecord(name=name, scope=scope, value=value)
        self._records[rid] = rec
        self._save()
        return rec

    def rotate(self, name: str, scope: str, new_value: str) -> KeyRecord:
        self._load()
        rid = f"{scope}/{name}"
        prev = self._records.get(rid)
        if prev is None:
            raise NotFound(rid)
        rec = KeyRecord(
            name=name,
            scope=scope,
            value=new_value,
            rotated_from=prev.created_at,
        )
        self._records[rid] = rec
        self._save()
        return rec

    def revoke(self, name: str, scope: str) -> KeyRecord:
        rec = self.get(name, scope)
        rec.status = "revoked"
        self._save()
        return rec

    def delete(self, name: str, scope: str) -> None:
        self._load()
        rid = f"{scope}/{name}"
        if rid not in self._records:
            raise NotFound(rid)
        del self._records[rid]
        self._save()

    def touch_used(self, name: str, scope: str, project: str | None) -> None:
        self._load()
        rid = f"{scope}/{name}"
        rec = self._records.get(rid)
        if rec is None:
            return
        rec.last_used_at = now_iso()
        if project:
            rec.last_injected_project = project
        self._save()

    # ---------- master rotation ----------

    def reset_master(self) -> dict:
        """Generate a new master key and re-encrypt the vault with it.

        Strategy:
          1. Load + decrypt the current vault into memory.
          2. Write a `.pre-reset.bak` copy of the current ciphertext (recovery
             aid: if anything goes wrong, this plus the old keychain entry can
             be used to recover).
          3. Generate a new Fernet key.
          4. Re-encrypt the vault with the new key to a temp file, then
             atomically replace the main vault file.
          5. Install the new key in the OS keychain, replacing the old one.

        If step 5 fails, the new vault file is already on disk but the keychain
        still holds the old key — the vault becomes unreadable until keychain
        is fixed. The .pre-reset.bak is kept until the next successful reset.
        """
        from . import keystore  # avoid import cycle at module scope

        self._load()  # requires OLD master; will raise VaultError if mismatch.
        records_copy = dict(self._records)
        old_bytes = self._path.read_bytes() if self._path.exists() else b""

        backup_path = self._path.with_suffix(".pre-reset.bak")
        if old_bytes:
            backup_path.write_bytes(old_bytes)
            try:
                os.chmod(backup_path, 0o600)
            except OSError:
                pass

        new_key = Fernet.generate_key()
        payload = {
            "version": VAULT_FORMAT_VERSION,
            "records": {rid: r.to_storage() for rid, r in records_copy.items()},
        }
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        enc_new = Fernet(new_key).encrypt(raw)

        ensure_vault_dir()
        directory = self._path.parent
        fd, tmp_path = tempfile.mkstemp(prefix=".vault.", suffix=".new.tmp", dir=str(directory))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(enc_new)
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, self._path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        keystore.replace_master(new_key)
        self._fernet = Fernet(new_key)
        return {
            "path": str(self._path),
            "backup": str(backup_path) if old_bytes else None,
            "records": len(records_copy),
        }

    # ---------- stats ----------

    def stats(self) -> dict:
        self._load()
        scopes: dict[str, int] = {}
        active = 0
        revoked = 0
        for r in self._records.values():
            scopes[r.scope] = scopes.get(r.scope, 0) + 1
            if r.status == "active":
                active += 1
            else:
                revoked += 1
        return {
            "total": len(self._records),
            "active": active,
            "revoked": revoked,
            "scopes": scopes,
            "path": str(self._path),
            "exists": self.exists(),
        }
