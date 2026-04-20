"""Writes resolved secrets into a project's .env file.

Merge policy:
  * preserve (default): keep all existing lines verbatim; only append keys
    that are missing.
  * overwrite: replace the value of existing KEY=... lines for any key we
    have a value for; append new ones at the end.

Either way, the file receives a short managed header on first write.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

from .resolver import Resolution

HEADER = "# Managed by vibe-secrets. Do not commit.\n"


def _shell_quote(value: str) -> str:
    if value == "":
        return ""
    special = any(c in value for c in " \t#\"'\n=$\\")
    if not special:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")
    return f'"{escaped}"'


def _parse_keys(text: str) -> set[str]:
    keys: set[str] = set()
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        raw_key = s.split("=", 1)[0].strip()
        if raw_key.startswith("export "):
            raw_key = raw_key[len("export ") :].strip()
        keys.add(raw_key)
    return keys


def write_env(
    project_path: Path | str,
    env_filename: str,
    resolutions: Iterable[Resolution],
    overwrite: bool = False,
) -> dict:
    project = Path(project_path).resolve()
    project.mkdir(parents=True, exist_ok=True)
    target = project / env_filename

    existing_text = target.read_text(encoding="utf-8") if target.exists() else ""
    existing_keys = _parse_keys(existing_text)

    updates: dict[str, tuple[str, str]] = {}  # name -> (value, scope)
    missing: list[str] = []
    revoked: list[str] = []

    for res in resolutions:
        if res.source == "revoked":
            revoked.append(res.name)
            continue
        if res.source == "missing" or res.record is None:
            missing.append(res.name)
            continue
        updates[res.name] = (res.record.value, res.resolved_scope or "")

    written: dict[str, str] = {}
    overwrote: dict[str, str] = {}
    skipped: dict[str, str] = {}

    if not existing_text:
        new_text = HEADER
    elif existing_text.startswith("# Managed by vibe-secrets"):
        new_text = existing_text
    else:
        new_text = existing_text

    if not new_text.endswith("\n") and new_text:
        new_text += "\n"

    if overwrite:
        # Line-by-line update for keys we have; append the rest.
        out_lines: list[str] = []
        remaining = dict(updates)
        for line in new_text.splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                out_lines.append(line)
                continue
            raw = s
            prefix_export = raw.startswith("export ")
            head = raw.split("=", 1)[0].strip()
            if prefix_export:
                head = head[len("export ") :].strip()
            if head in remaining:
                val, scope = remaining.pop(head)
                prefix = "export " if prefix_export else ""
                out_lines.append(f"{prefix}{head}={_shell_quote(val)}")
                overwrote[head] = scope
                written[head] = scope
            else:
                out_lines.append(line)
        for k, (val, scope) in remaining.items():
            out_lines.append(f"{k}={_shell_quote(val)}")
            written[k] = scope
        body = "\n".join(out_lines)
        if not body.endswith("\n"):
            body += "\n"
        final = body if body.startswith("# Managed by vibe-secrets") else (HEADER + body)
    else:
        # Preserve: only append keys not already present.
        body = new_text
        for k, (val, scope) in updates.items():
            if k in existing_keys:
                skipped[k] = "exists"
                continue
            body += f"{k}={_shell_quote(val)}\n"
            written[k] = scope
        final = body if body.startswith("# Managed by vibe-secrets") else (HEADER + body)

    target.write_text(final, encoding="utf-8")
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass

    return {
        "path": str(target),
        "written": written,
        "overwrote": overwrote,
        "skipped": skipped,
        "missing": missing,
        "revoked": revoked,
    }
