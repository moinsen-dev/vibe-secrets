"""Overlay scope resolution: project:<name>:<env> → global."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .models import GLOBAL_SCOPE, KeyRecord
from .vault import Vault


@dataclass
class Resolution:
    name: str
    record: KeyRecord | None
    resolved_scope: str | None
    source: str  # "project" | "global" | "revoked" | "missing"

    @property
    def ok(self) -> bool:
        return self.record is not None and self.record.status == "active"

    def to_public(self) -> dict:
        return {
            "name": self.name,
            "source": self.source,
            "scope": self.resolved_scope,
            "status": self.record.status if self.record else None,
        }


def resolve(
    vault: Vault,
    names: Iterable[str],
    project: str | None,
    env: str | None,
) -> list[Resolution]:
    """For each name, try project scope, then global. Never returns values to callers;
    the returned Resolution holds the record in-memory for writers to consume.
    """
    out: list[Resolution] = []
    project_scope = f"project:{project}:{env}" if (project and env) else None
    for n in names:
        rec = None
        source = "missing"
        scope_used: str | None = None

        if project_scope:
            p = vault.try_get(n, project_scope)
            if p is not None:
                if p.status == "active":
                    rec = p
                    source = "project"
                    scope_used = p.scope
                else:
                    source = "revoked"
                    scope_used = p.scope

        if rec is None and source == "missing":
            g = vault.try_get(n, GLOBAL_SCOPE)
            if g is not None:
                if g.status == "active":
                    rec = g
                    source = "global"
                    scope_used = g.scope
                else:
                    source = "revoked"
                    scope_used = g.scope

        out.append(
            Resolution(
                name=n,
                record=rec,
                resolved_scope=scope_used,
                source=source,
            )
        )
    return out
