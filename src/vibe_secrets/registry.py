"""Local project registry — plain-JSON map of which projects use which secrets.

Contains no secret values, only metadata:
  * project path (resolved, absolute)
  * project name (declared in .vault.yaml or folder basename)
  * default env
  * keys injected per env
  * timestamps

Lets `fanout` know which projects to update after a rotation, and `projects`
enumerate onboarded projects.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .config import ensure_vault_dir, vault_dir
from .models import now_iso

REGISTRY_VERSION = 1


def _registry_file() -> Path:
    return vault_dir() / "projects.json"


def load() -> dict:
    path = _registry_file()
    if not path.exists():
        return {"version": REGISTRY_VERSION, "projects": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": REGISTRY_VERSION, "projects": {}}
    if not isinstance(data, dict) or "projects" not in data:
        return {"version": REGISTRY_VERSION, "projects": {}}
    return data


def save(reg: dict) -> None:
    ensure_vault_dir()
    path = _registry_file()
    directory = path.parent
    fd, tmp_path = tempfile.mkstemp(prefix=".registry.", suffix=".tmp", dir=str(directory))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(reg, indent=2, ensure_ascii=False))
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _key(project_path: str | Path) -> str:
    return str(Path(project_path).resolve())


def register(
    project_path: str | Path,
    name: str,
    default_env: str = "dev",
) -> dict:
    reg = load()
    k = _key(project_path)
    entry = reg["projects"].setdefault(k, {})
    entry["name"] = name
    entry["default_env"] = default_env
    entry.setdefault("keys", {})
    entry.setdefault("registered_at", now_iso())
    entry["updated_at"] = now_iso()
    save(reg)
    return entry


def record_inject(
    project_path: str | Path,
    name: str,
    env: str,
    keys: list[str],
) -> None:
    reg = load()
    k = _key(project_path)
    entry = reg["projects"].setdefault(k, {"name": name, "default_env": env, "keys": {}})
    entry["name"] = name
    entry.setdefault("default_env", env)
    entry.setdefault("keys", {})
    existing = set(entry["keys"].get(env, []))
    existing.update(keys)
    entry["keys"][env] = sorted(existing)
    entry["last_sync"] = now_iso()
    entry["updated_at"] = now_iso()
    save(reg)


def projects_using(name: str) -> list[tuple[str, str, str]]:
    """Return list of (project_path, project_name, env) entries that reference `name`."""
    reg = load()
    out: list[tuple[str, str, str]] = []
    for path, entry in reg["projects"].items():
        for env, keys in (entry.get("keys") or {}).items():
            if name in keys:
                out.append((path, entry.get("name") or Path(path).name, env))
    return out


def get(project_path: str | Path) -> dict | None:
    reg = load()
    return reg["projects"].get(_key(project_path))


def list_all() -> list[dict]:
    reg = load()
    out = []
    for path, entry in sorted(reg["projects"].items()):
        out.append({"path": path, **entry})
    return out


def unregister(project_path: str | Path) -> bool:
    reg = load()
    k = _key(project_path)
    if k in reg["projects"]:
        del reg["projects"][k]
        save(reg)
        return True
    return False
