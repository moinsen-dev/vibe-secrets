from __future__ import annotations

from pathlib import Path

import pytest

from vibe_secrets import installer, templates


@pytest.fixture()
def skills_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "claude" / "skills"
    monkeypatch.setenv("CLAUDE_SKILLS_HOME", str(home))
    return home


def test_install_writes_file(skills_home: Path) -> None:
    r = installer.install_claude_skill()
    assert r.status == "installed"
    path = skills_home / "vibe-secrets" / "SKILL.md"
    assert path.exists()
    assert path.read_text() == templates.claude_skill_md()


def test_install_idempotent(skills_home: Path) -> None:
    installer.install_claude_skill()
    r2 = installer.install_claude_skill()
    assert r2.status == "unchanged"


def test_install_refuses_to_overwrite_foreign_file(skills_home: Path) -> None:
    path = skills_home / "vibe-secrets" / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\nname: foreign\n---\n# not ours\n")
    r = installer.install_claude_skill(force=False)
    assert r.status == "skipped-exists"
    assert path.read_text().startswith("---\nname: foreign\n")


def test_install_force_overwrites(skills_home: Path) -> None:
    path = skills_home / "vibe-secrets" / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("old content\n")
    r = installer.install_claude_skill(force=True)
    assert r.status == "installed"
    assert path.read_text() == templates.claude_skill_md()


def test_uninstall_removes_file(skills_home: Path) -> None:
    installer.install_claude_skill()
    r = installer.uninstall_claude_skill()
    assert r.status == "uninstalled"
    assert not (skills_home / "vibe-secrets" / "SKILL.md").exists()


def test_status_reports_not_present(skills_home: Path) -> None:
    results = installer.skill_status()
    assert results[0].status == "not-present"


def test_status_reports_installed(skills_home: Path) -> None:
    installer.install_claude_skill()
    results = installer.skill_status()
    assert results[0].status == "installed"


def test_status_detects_outdated(skills_home: Path) -> None:
    path = skills_home / "vibe-secrets" / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stale version\n")
    results = installer.skill_status()
    assert results[0].status == "outdated"


# ---------- templates content contract ----------


def test_claude_skill_contains_rules() -> None:
    body = templates.claude_skill_md()
    assert "name: vibe-secrets" in body
    assert "Never ask the user to paste" in body
    assert "vibe-secrets agent inject" in body
    assert "vibe-secrets agent status" in body


def test_all_block_renderers_produce_markers() -> None:
    for render in (
        templates.agents_block,
        templates.claude_md_block,
        templates.copilot_block,
        templates.windsurf_block,
    ):
        block = render("demo", "dev")
        assert templates.BEGIN_MARKER in block
        assert templates.END_MARKER in block
        assert "demo" in block


def test_cursor_mdc_has_frontmatter() -> None:
    mdc = templates.cursor_mdc("demo", "dev")
    assert mdc.startswith("---\n")
    assert "alwaysApply: true" in mdc
    assert "Never ask the user to paste" in mdc
