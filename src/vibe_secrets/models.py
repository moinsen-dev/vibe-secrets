"""Domain types for the vault."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

GLOBAL_SCOPE = "global"
_PROJECT_SCOPE_RE = re.compile(r"^project:([A-Za-z0-9._-]+):([A-Za-z0-9._-]+)$")
_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,}$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def is_valid_scope(scope: str) -> bool:
    if scope == GLOBAL_SCOPE:
        return True
    return bool(_PROJECT_SCOPE_RE.match(scope))


def parse_scope(scope: str) -> tuple[str, str | None, str | None]:
    """Return (kind, project, env). kind is 'global' or 'project'."""
    if scope == GLOBAL_SCOPE:
        return "global", None, None
    m = _PROJECT_SCOPE_RE.match(scope)
    if not m:
        raise ValueError(f"Invalid scope {scope!r}. Use 'global' or 'project:<name>:<env>'.")
    return "project", m.group(1), m.group(2)


def is_valid_name(name: str) -> bool:
    return bool(_NAME_RE.match(name))


def validate_name(name: str) -> None:
    if not is_valid_name(name):
        raise ValueError(
            f"Invalid secret name {name!r}. Use UPPER_SNAKE_CASE, min 2 chars, "
            f"starting with a letter."
        )


def validate_scope(scope: str) -> None:
    if not is_valid_scope(scope):
        raise ValueError(f"Invalid scope {scope!r}. Use 'global' or 'project:<name>:<env>'.")


@dataclass
class KeyRecord:
    name: str
    scope: str
    value: str
    created_at: str = field(default_factory=now_iso)
    last_used_at: str | None = None
    last_injected_project: str | None = None
    status: str = "active"  # "active" | "revoked"
    rotated_from: str | None = None  # previous created_at

    def record_id(self) -> str:
        return f"{self.scope}/{self.name}"

    def to_public(self) -> dict:
        d = asdict(self)
        d.pop("value", None)
        return d

    def to_storage(self) -> dict:
        return asdict(self)

    @classmethod
    def from_storage(cls, data: dict) -> KeyRecord:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})
