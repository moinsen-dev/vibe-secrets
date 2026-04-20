from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from vibe_secrets.cli import main


def test_completion_show_bash() -> None:
    runner = CliRunner()
    r = runner.invoke(main, ["completion", "show", "bash"])
    assert r.exit_code == 0
    assert "_VIBE_SECRETS_COMPLETE=bash_source" in r.output


def test_completion_show_zsh() -> None:
    runner = CliRunner()
    r = runner.invoke(main, ["completion", "show", "zsh"])
    assert r.exit_code == 0
    assert "_VIBE_SECRETS_COMPLETE=zsh_source" in r.output


def test_completion_show_fish() -> None:
    runner = CliRunner()
    r = runner.invoke(main, ["completion", "show", "fish"])
    assert r.exit_code == 0
    assert "_VIBE_SECRETS_COMPLETE=fish_source" in r.output


def test_completion_install_appends(tmp_path: Path, vault_env: Path) -> None:
    rc = tmp_path / "rcfile"
    rc.write_text("# existing content\n")
    runner = CliRunner()
    r = runner.invoke(main, ["completion", "install", "zsh", "--rc", str(rc)])
    assert r.exit_code == 0
    content = rc.read_text()
    assert "# existing content" in content
    assert "# vibe-secrets completion" in content
    assert "_VIBE_SECRETS_COMPLETE=zsh_source" in content


def test_completion_install_is_idempotent(tmp_path: Path, vault_env: Path) -> None:
    rc = tmp_path / "rc2"
    runner = CliRunner()
    r1 = runner.invoke(main, ["completion", "install", "bash", "--rc", str(rc)])
    assert r1.exit_code == 0
    first_size = rc.stat().st_size
    r2 = runner.invoke(main, ["completion", "install", "bash", "--rc", str(rc)])
    assert r2.exit_code == 0
    assert rc.stat().st_size == first_size


def test_quickstart_shown_on_no_args() -> None:
    runner = CliRunner()
    r = runner.invoke(main, [])
    assert r.exit_code == 0
    assert "First time on this machine" in r.output
    assert "bootstrap" in r.output
