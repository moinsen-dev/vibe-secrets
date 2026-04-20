from __future__ import annotations

from pathlib import Path

import pytest

from vibe_secrets import projectops


def test_auto_detect_cursor(tmp_path: Path, vault_env: Path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    (project / ".cursor").mkdir()
    r = projectops.setup_project(project, "demo", "dev")
    cursor_path = project / ".cursor" / "rules" / "vibe-secrets.mdc"
    assert "cursor" in r["emits"]
    assert cursor_path.exists()
    content = cursor_path.read_text()
    assert content.startswith("---\n")
    assert "alwaysApply: true" in content


def test_auto_detect_copilot(tmp_path: Path, vault_env: Path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    (project / ".github").mkdir()
    r = projectops.setup_project(project, "demo", "dev")
    copilot_path = project / ".github" / "copilot-instructions.md"
    assert "copilot" in r["emits"]
    assert copilot_path.exists()
    assert "vibe-secrets:begin" in copilot_path.read_text()


def test_auto_detect_windsurf_only_if_file_present(tmp_path: Path, vault_env: Path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    # No .windsurfrules — do not create it.
    r1 = projectops.setup_project(project, "demo", "dev")
    assert "windsurf" not in r1["emits"]
    assert not (project / ".windsurfrules").exists()

    # With .windsurfrules — update it.
    (project / ".windsurfrules").write_text("# existing rules\n")
    r2 = projectops.setup_project(project, "demo", "dev")
    assert "windsurf" in r2["emits"]
    text = (project / ".windsurfrules").read_text()
    assert "# existing rules" in text
    assert "vibe-secrets:begin" in text


def test_explicit_emit_all(tmp_path: Path, vault_env: Path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    r = projectops.setup_project(project, "demo", "dev", emit=["all"])
    assert set(r["emits"].keys()) == {
        "agents",
        "claude",
        "cursor",
        "copilot",
        "windsurf",
    }
    assert (project / ".cursor" / "rules" / "vibe-secrets.mdc").exists()
    assert (project / ".github" / "copilot-instructions.md").exists()
    assert (project / ".windsurfrules").exists()


def test_explicit_emit_cursor_only(tmp_path: Path, vault_env: Path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    r = projectops.setup_project(project, "demo", "dev", emit=["cursor"])
    assert set(r["emits"].keys()) == {"cursor"}
    assert not (project / "AGENTS.md").exists()
    assert (project / ".cursor" / "rules" / "vibe-secrets.mdc").exists()


def test_invalid_emit_rejected(tmp_path: Path, vault_env: Path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    with pytest.raises(ValueError):
        projectops.setup_project(project, "demo", "dev", emit=["bogus"])


def test_comma_separated_emit(tmp_path: Path, vault_env: Path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    r = projectops.setup_project(project, "demo", "dev", emit=["agents,cursor"])
    assert set(r["emits"].keys()) == {"agents", "cursor"}


def test_cursor_mdc_is_idempotent(tmp_path: Path, vault_env: Path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    (project / ".cursor").mkdir()
    projectops.setup_project(project, "demo", "dev")
    first = (project / ".cursor" / "rules" / "vibe-secrets.mdc").read_text()
    projectops.setup_project(project, "demo", "dev")
    second = (project / ".cursor" / "rules" / "vibe-secrets.mdc").read_text()
    assert first == second


def test_copilot_block_idempotent(tmp_path: Path, vault_env: Path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    (project / ".github").mkdir()
    projectops.setup_project(project, "demo", "dev")
    first = (project / ".github" / "copilot-instructions.md").read_text()
    projectops.setup_project(project, "demo", "dev")
    second = (project / ".github" / "copilot-instructions.md").read_text()
    # Must have exactly one block (not re-appended).
    assert second.count("vibe-secrets:begin") == 1
    assert first == second
