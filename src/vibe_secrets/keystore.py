"""Master-key storage in the OS keychain.

The master key is a 32-byte Fernet key (url-safe base64). It is never written to
disk by this tool; it lives in the operating system's credential store:
  * macOS:   Keychain
  * Linux:   Secret Service (GNOME Keyring / KWallet)
  * Windows: Credential Manager

For automated tests, set VIBE_SECRETS_MASTER to a base64 Fernet key to bypass
the keyring entirely.
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet

try:  # keyring is an optional-looking import only because tests may skip it
    import keyring
    from keyring.errors import KeyringError, NoKeyringError
except Exception:  # pragma: no cover
    keyring = None  # type: ignore
    KeyringError = Exception  # type: ignore
    NoKeyringError = Exception  # type: ignore


SERVICE = "vibe-secrets"
ACCOUNT = "master-v1"
ENV_OVERRIDE = "VIBE_SECRETS_MASTER"


class KeystoreError(Exception):
    pass


def _override() -> bytes | None:
    val = os.environ.get(ENV_OVERRIDE)
    if val:
        return val.encode("ascii")
    return None


def has_master() -> bool:
    if _override() is not None:
        return True
    if keyring is None:
        return False
    try:
        return keyring.get_password(SERVICE, ACCOUNT) is not None
    except (KeyringError, NoKeyringError) as e:
        raise KeystoreError(f"Keyring unavailable: {e}") from e


def create_master() -> bytes:
    """Generate and persist a new master key. Raises if one already exists."""
    if has_master():
        raise KeystoreError("Master key already exists. Use `reset-master` to replace it.")
    key = Fernet.generate_key()
    if _override() is not None:
        # In override mode we can't 'create' — the env is authoritative.
        return _override()  # type: ignore[return-value]
    if keyring is None:
        raise KeystoreError("Python 'keyring' library is required for keychain storage.")
    try:
        keyring.set_password(SERVICE, ACCOUNT, key.decode("ascii"))
    except (KeyringError, NoKeyringError) as e:
        raise KeystoreError(f"Failed to store master in keyring: {e}") from e
    return key


def load_master() -> bytes:
    ov = _override()
    if ov is not None:
        return ov
    if keyring is None:
        raise KeystoreError("Python 'keyring' library is required to read the master key.")
    try:
        encoded = keyring.get_password(SERVICE, ACCOUNT)
    except (KeyringError, NoKeyringError) as e:
        raise KeystoreError(f"Keyring unavailable: {e}") from e
    if not encoded:
        raise KeystoreError("No master key found. Run `vibe-secrets init` first.")
    return encoded.encode("ascii")


def delete_master() -> None:
    if _override() is not None:
        return
    if keyring is None:
        return
    try:
        keyring.delete_password(SERVICE, ACCOUNT)
    except (KeyringError, NoKeyringError):
        pass


def replace_master(new_key: bytes) -> None:
    """Install `new_key` as the master, replacing any existing entry. No-op in env-override mode."""
    if _override() is not None:
        return
    if keyring is None:
        raise KeystoreError("Python 'keyring' library is required for keychain storage.")
    try:
        keyring.set_password(SERVICE, ACCOUNT, new_key.decode("ascii"))
    except (KeyringError, NoKeyringError) as e:
        raise KeystoreError(f"Failed to store master in keyring: {e}") from e
