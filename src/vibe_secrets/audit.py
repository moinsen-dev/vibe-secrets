"""Append-only local audit log."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from .config import audit_file, ensure_vault_dir


def _actor(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    return os.environ.get("VIBE_SECRETS_ACTOR", "cli")


def log(op: str, **fields: Any) -> None:
    """Append a single event to the audit log. Never raises on I/O errors."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "op": op,
        "actor": _actor(fields.pop("actor", None)),
    }
    for k, v in fields.items():
        if v is not None:
            entry[k] = v
    try:
        ensure_vault_dir()
        path = audit_file()
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError:
        # Auditing must never break the main operation.
        pass


def tail(limit: int = 50) -> list[dict]:
    path = audit_file()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
