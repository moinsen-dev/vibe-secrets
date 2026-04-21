"""Project-level operations: setup, import, sync, diff, fanout.

All of these operate on a project folder on disk and may touch the vault
and the project registry. None of them expose raw secret values in their
return values.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from . import envwriter, registry, templates
from .models import GLOBAL_SCOPE, validate_name, validate_scope
from .resolver import Resolution, resolve
from .scanner import scan
from .templates import BEGIN_MARKER, END_MARKER
from .vault import AlreadyExists, NotFound, Vault

# Known emission targets for setup(). "agents" and "claude" are always emitted;
# the rest are opt-in via --emit or auto-detected by directory presence.
EMIT_TARGETS: dict[str, str] = {
    "agents": "AGENTS.md",
    "claude": "CLAUDE.md",
    "cursor": ".cursor/rules/vibe-secrets.mdc",
    "copilot": ".github/copilot-instructions.md",
    "windsurf": ".windsurfrules",
}


GITIGNORE_LINES = [".env", ".env.*", "!.env.example", ".vault.lock"]


# ---------- setup ----------


def _read_vault_yaml(project: Path) -> dict:
    path = project / ".vault.yaml"
    if not path.exists():
        return {}
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_vault_yaml(project: Path, project_name: str, default_env: str) -> str:
    import yaml

    path = project / ".vault.yaml"
    data = _read_vault_yaml(project)
    data["project"] = project_name
    data.setdefault("default_env", default_env)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return str(path)


def _upsert_block(path: Path, block: str) -> str:
    """Insert or replace a marker-delimited block in a file. Idempotent."""
    # Ensure block ends with exactly one newline.
    block = block.rstrip() + "\n"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(block, encoding="utf-8")
        return "created"
    text = path.read_text(encoding="utf-8")
    if BEGIN_MARKER in text and END_MARKER in text:
        before, _, rest = text.partition(BEGIN_MARKER)
        _, _, after = rest.partition(END_MARKER)
        before_clean = before.rstrip()
        after_clean = after.lstrip("\n")
        prefix = (before_clean + "\n\n") if before_clean else ""
        suffix_after = ("\n" + after_clean) if after_clean else "\n"
        new_text = prefix + block.rstrip() + suffix_after
        if not new_text.endswith("\n"):
            new_text += "\n"
        path.write_text(new_text, encoding="utf-8")
        return "updated"
    suffix = "\n\n" if not text.endswith("\n\n") else ""
    path.write_text(text + suffix + block, encoding="utf-8")
    return "inserted"


def _write_cursor_rule(path: Path, content: str) -> str:
    """Cursor rules live in .cursor/rules/ as .mdc files with frontmatter.
    We own the entire file (no marker-merging) because Cursor expects a single
    frontmatter block per file. Idempotent: skip if identical.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return "unchanged"
    existed = path.exists()
    path.write_text(content, encoding="utf-8")
    return "updated" if existed else "created"


def detect_emit_targets(project: Path) -> list[str]:
    """Return the set of emit targets to use by auto-detection.

    Always: agents, claude.
    Opt-in by directory presence:
      * cursor   — .cursor/ directory exists
      * copilot  — .github/ directory exists
      * windsurf — .windsurfrules exists (we update, don't create)
    """
    targets = ["agents", "claude"]
    if (project / ".cursor").is_dir():
        targets.append("cursor")
    if (project / ".github").is_dir():
        targets.append("copilot")
    if (project / ".windsurfrules").exists():
        targets.append("windsurf")
    return targets


def _normalize_emit(emit: Iterable[str] | None) -> list[str] | None:
    if emit is None:
        return None
    out: list[str] = []
    for e in emit:
        for piece in str(e).split(","):
            piece = piece.strip().lower()
            if not piece:
                continue
            if piece == "all":
                return list(EMIT_TARGETS.keys())
            if piece not in EMIT_TARGETS:
                raise ValueError(
                    f"Unknown emit target {piece!r}. Valid: {', '.join(EMIT_TARGETS.keys())}, all."
                )
            if piece not in out:
                out.append(piece)
    return out


def _upsert_gitignore(project: Path) -> dict:
    path = project / ".gitignore"
    lines: list[str] = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    existing = {ln.strip() for ln in lines}
    added: list[str] = []
    for line in GITIGNORE_LINES:
        if line not in existing:
            lines.append(line)
            added.append(line)
    if added or not path.exists():
        body = "\n".join(lines).rstrip() + "\n" if lines else ""
        path.write_text(body, encoding="utf-8")
    return {"path": str(path), "added": added}


def setup_project(
    project_path: Path | str,
    project_name: str | None = None,
    default_env: str = "dev",
    emit: Iterable[str] | None = None,
) -> dict:
    """Onboard a project: write .vault.yaml, agent rules files, and .gitignore.

    Args:
        project_path: project root folder.
        project_name: explicit name; else .vault.yaml or folder basename.
        default_env: default env for the project.
        emit: iterable of emit target names (agents, claude, cursor, copilot,
              windsurf, or 'all'). None = auto-detect based on project layout.
    """
    project = Path(project_path).resolve()
    project.mkdir(parents=True, exist_ok=True)
    existing_yaml = _read_vault_yaml(project)
    name = (
        project_name
        or (existing_yaml.get("project") if isinstance(existing_yaml.get("project"), str) else None)
        or project.name
    )
    env = default_env or existing_yaml.get("default_env") or "dev"

    yaml_path = _write_vault_yaml(project, name, env)

    normalized = _normalize_emit(emit)
    target_set: list[str] = normalized if normalized is not None else detect_emit_targets(project)

    results: dict[str, dict] = {}
    for target in target_set:
        if target == "agents":
            status = _upsert_block(project / "AGENTS.md", templates.agents_block(name, env))
            results[target] = {"path": str(project / "AGENTS.md"), "status": status}
        elif target == "claude":
            status = _upsert_block(project / "CLAUDE.md", templates.claude_md_block(name, env))
            results[target] = {"path": str(project / "CLAUDE.md"), "status": status}
        elif target == "cursor":
            target_path = project / ".cursor" / "rules" / "vibe-secrets.mdc"
            status = _write_cursor_rule(target_path, templates.cursor_mdc(name, env))
            results[target] = {"path": str(target_path), "status": status}
        elif target == "copilot":
            target_path = project / ".github" / "copilot-instructions.md"
            status = _upsert_block(target_path, templates.copilot_block(name, env))
            results[target] = {"path": str(target_path), "status": status}
        elif target == "windsurf":
            target_path = project / ".windsurfrules"
            status = _upsert_block(target_path, templates.windsurf_block(name, env))
            results[target] = {"path": str(target_path), "status": status}

    gi = _upsert_gitignore(project)
    registry.register(project, name, env)

    return {
        "project": str(project),
        "project_name": name,
        "default_env": env,
        "vault_yaml": yaml_path,
        "emits": results,
        "gitignore": gi,
        # Legacy shortcuts kept for backwards compatibility with earlier output.
        "agents_md": results.get("agents", {}).get("status", "skipped"),
        "claude_md": results.get("claude", {}).get("status", "skipped"),
    }


# ---------- import ----------

MANAGED_HEADER = "Managed by vibe-secrets"


def parse_env_file(path: Path) -> list[tuple[str, str]]:
    """Parse KEY=value lines from an .env-style file. Comments and blanks ignored.
    Values surrounded by matching single or double quotes are unquoted.
    """
    out: list[tuple[str, str]] = []
    if not path.exists():
        return out
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return out
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        head, _, value = s.partition("=")
        head = head.strip()
        if head.startswith("export "):
            head = head[len("export ") :].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
            value = (
                value.replace("\\\\", "\x00")
                .replace("\\n", "\n")
                .replace("\\t", "\t")
                .replace('\\"', '"')
                .replace("\x00", "\\")
            )
        elif len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1]
        out.append((head, value))
    return out


def is_managed(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        head = path.read_text(encoding="utf-8", errors="ignore")[:200]
    except OSError:
        return False
    return MANAGED_HEADER in head


def suggest_scope(filename: str, project_name: str) -> str:
    """Suggest a default scope based on the .env filename. Ambiguous → global."""
    n = filename
    if n in (".env", ".env.example", ".env.sample"):
        return GLOBAL_SCOPE
    lower = n.lower()
    if any(m in lower for m in (".local", ".development", ".dev")):
        return f"project:{project_name}:dev"
    if any(m in lower for m in (".production", ".prod")):
        return f"project:{project_name}:prod"
    if ".test" in lower:
        return f"project:{project_name}:test"
    return GLOBAL_SCOPE


@dataclass
class ImportDecision:
    name: str
    scope: str
    action: str  # "add" | "rotate" | "skip"
    source_file: str


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def collect_import_candidates(
    project: Path,
    include_managed: bool = False,
) -> list[tuple[Path, list[tuple[str, str]]]]:
    project = Path(project).resolve()
    result: list[tuple[Path, list[tuple[str, str]]]] = []
    seen: set[Path] = set()
    for p in sorted(project.glob(".env*")):
        if not p.is_file():
            continue
        resolved = p.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if not include_managed and is_managed(p):
            continue
        entries = parse_env_file(p)
        if not entries:
            continue
        result.append((p, entries))
    return result


def apply_import(
    vault: Vault,
    decisions: Iterable[ImportDecision],
    value_lookup: dict[tuple[str, str], str],
) -> dict:
    """Apply a batch of import decisions. value_lookup maps (source_file, name)
    to the raw value parsed from that file — kept out of the public return."""
    added: list[tuple[str, str]] = []
    rotated: list[tuple[str, str]] = []
    skipped: list[tuple[str, str, str]] = []  # (name, scope, reason)
    for d in decisions:
        try:
            validate_name(d.name)
            validate_scope(d.scope)
        except ValueError as e:
            skipped.append((d.name, d.scope, f"invalid: {e}"))
            continue
        value = value_lookup.get((d.source_file, d.name))
        if value is None:
            skipped.append((d.name, d.scope, "value-missing"))
            continue
        if d.action == "skip":
            skipped.append((d.name, d.scope, "user-skipped"))
            continue
        try:
            if d.action == "rotate":
                try:
                    vault.rotate(d.name, d.scope, value)
                    rotated.append((d.name, d.scope))
                except NotFound:
                    vault.add(d.name, d.scope, value)
                    added.append((d.name, d.scope))
            else:  # "add"
                try:
                    vault.add(d.name, d.scope, value)
                    added.append((d.name, d.scope))
                except AlreadyExists:
                    skipped.append((d.name, d.scope, "already-exists"))
        except Exception as e:  # pragma: no cover
            skipped.append((d.name, d.scope, f"error: {e}"))
    return {"added": added, "rotated": rotated, "skipped": skipped}


# ---------- sync / diff ----------


@dataclass
class DiffReport:
    match: list[str]
    differ: list[str]
    only_in_env: list[str]
    only_in_vault: list[str]
    missing_in_vault: list[str]
    revoked_in_vault: list[str]

    def to_public(self) -> dict:
        return {
            "match": sorted(self.match),
            "differ": sorted(self.differ),
            "only_in_env": sorted(self.only_in_env),
            "only_in_vault": sorted(self.only_in_vault),
            "missing_in_vault": sorted(self.missing_in_vault),
            "revoked_in_vault": sorted(self.revoked_in_vault),
        }


def diff_project(
    vault: Vault,
    project: Path | str,
    project_name: str,
    env: str,
    names: Iterable[str] | None = None,
    env_filename: str = ".env",
) -> DiffReport:
    project = Path(project).resolve()
    env_path = project / env_filename
    name_list = sorted(set(names)) if names else sorted(scan(project, exclude=[env_path]))
    existing: dict[str, str] = {}
    if env_path.exists():
        for k, v in parse_env_file(env_path):
            existing[k] = v

    resolutions = resolve(vault, name_list, project_name, env)
    match: list[str] = []
    differ: list[str] = []
    only_in_vault: list[str] = []
    missing: list[str] = []
    revoked: list[str] = []

    scanned_names = set(name_list)
    for r in resolutions:
        if r.source == "missing":
            missing.append(r.name)
            continue
        if r.source == "revoked":
            revoked.append(r.name)
            continue
        if r.record is None:
            continue
        if r.name not in existing:
            only_in_vault.append(r.name)
            continue
        if existing[r.name] == r.record.value:
            match.append(r.name)
        else:
            differ.append(r.name)

    only_in_env = [k for k in existing if k not in scanned_names]
    return DiffReport(
        match=match,
        differ=differ,
        only_in_env=only_in_env,
        only_in_vault=only_in_vault,
        missing_in_vault=missing,
        revoked_in_vault=revoked,
    )


def sync_project(
    vault: Vault,
    project: Path | str,
    project_name: str,
    env: str,
    env_filename: str = ".env",
    overwrite: bool = True,
    names: Iterable[str] | None = None,
) -> dict:
    """Scan + resolve + inject, update registry, return a value-blind summary."""
    project = Path(project).resolve()
    env_path = project / env_filename
    name_list = sorted(set(names)) if names else sorted(scan(project, exclude=[env_path]))
    resolutions: list[Resolution] = resolve(vault, name_list, project_name, env)
    write = envwriter.write_env(project, env_filename, resolutions, overwrite=overwrite)
    for n, scope in write["written"].items():
        vault.touch_used(n, scope, project_name)
    if write["written"]:
        registry.record_inject(project, project_name, env, list(write["written"].keys()))
    return {
        "project": str(project),
        "project_name": project_name,
        "env": env,
        "path": write["path"],
        "written": list(write["written"].keys()),
        "overwrote": list(write["overwrote"].keys()),
        "skipped": write["skipped"],
        "missing": write["missing"],
        "revoked": write["revoked"],
        "scanned": name_list,
    }


# ---------- fanout ----------


def fanout_key(
    vault: Vault,
    name: str,
    env_filename: str = ".env",
    overwrite: bool = True,
) -> list[dict]:
    """Re-inject `name` into every registered project that uses it."""
    targets = registry.projects_using(name)
    results: list[dict] = []
    for path, pname, env in targets:
        resolutions = resolve(vault, [name], pname, env)
        if not any(r.ok for r in resolutions):
            results.append(
                {
                    "path": path,
                    "project_name": pname,
                    "env": env,
                    "status": "unavailable",
                    "source": resolutions[0].source if resolutions else "missing",
                }
            )
            continue
        out = envwriter.write_env(Path(path), env_filename, resolutions, overwrite=overwrite)
        for k, scope in out["written"].items():
            vault.touch_used(k, scope, pname)
        if out["written"]:
            registry.record_inject(path, pname, env, list(out["written"].keys()))
        results.append(
            {
                "path": path,
                "project_name": pname,
                "env": env,
                "status": "ok" if out["written"] or out["overwrote"] else "noop",
                "written": list(out["written"].keys()),
                "overwrote": list(out["overwrote"].keys()),
                "skipped": out["skipped"],
            }
        )
    return results
