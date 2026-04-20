"""User-level installer for AI-assistant integrations.

Currently supports Claude Code's user-level skill directory. Per-project
emissions (Cursor, Copilot, Windsurf) live in `projectops.py`.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import templates

CLAUDE_SKILL_DIR_ENV = "CLAUDE_SKILLS_HOME"


def claude_skill_dir() -> Path:
    """Return the Claude Code user-level skills directory.

    Overridable via CLAUDE_SKILLS_HOME for tests and unusual setups.
    """
    override = os.environ.get(CLAUDE_SKILL_DIR_ENV)
    if override:
        return Path(override)
    return Path.home() / ".claude" / "skills"


def claude_skill_path() -> Path:
    return claude_skill_dir() / "vibe-secrets" / "SKILL.md"


@dataclass
class InstallResult:
    target: str
    path: str
    status: str  # "installed" | "unchanged" | "skipped-exists" | "uninstalled" | "not-present"
    detail: str | None = None

    def to_public(self) -> dict:
        d = {"target": self.target, "path": self.path, "status": self.status}
        if self.detail:
            d["detail"] = self.detail
        return d


def install_claude_skill(force: bool = False) -> InstallResult:
    """Write the Claude Code skill into ~/.claude/skills/vibe-secrets/SKILL.md."""
    target = claude_skill_path()
    want = templates.claude_skill_md()

    if target.exists():
        have = target.read_text(encoding="utf-8")
        if have == want:
            return InstallResult("claude", str(target), "unchanged")
        if not force:
            return InstallResult(
                "claude",
                str(target),
                "skipped-exists",
                "File exists with different content. Use --force to overwrite.",
            )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(want, encoding="utf-8")
    try:
        os.chmod(target, 0o644)
    except OSError:
        pass
    return InstallResult("claude", str(target), "installed")


def uninstall_claude_skill() -> InstallResult:
    target = claude_skill_path()
    if not target.exists():
        return InstallResult("claude", str(target), "not-present")
    try:
        target.unlink()
    except OSError as e:  # pragma: no cover
        return InstallResult("claude", str(target), "error", str(e))
    parent = target.parent
    try:
        if parent.exists() and not any(parent.iterdir()):
            shutil.rmtree(parent)
    except OSError:
        pass
    return InstallResult("claude", str(target), "uninstalled")


def skill_status() -> list[InstallResult]:
    """Report the status of each user-level integration target."""
    target = claude_skill_path()
    if not target.exists():
        return [InstallResult("claude", str(target), "not-present")]
    try:
        have = target.read_text(encoding="utf-8")
    except OSError:
        return [InstallResult("claude", str(target), "error")]
    if have == templates.claude_skill_md():
        return [InstallResult("claude", str(target), "installed")]
    return [
        InstallResult(
            "claude",
            str(target),
            "outdated",
            "Content differs from current package version. Run "
            "`vibe-secrets skill install --force` to refresh.",
        )
    ]
