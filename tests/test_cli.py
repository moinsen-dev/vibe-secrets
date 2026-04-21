"""Smoke tests for the CLI: raw values must never leak in non-reveal commands."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from vibe_secrets.cli import main


def _init_and_add(runner: CliRunner, name: str, scope: str, value: str) -> None:
    r = runner.invoke(main, ["init"])
    if r.exit_code != 0 and "already exists" not in r.output.lower():
        raise AssertionError(r.output)
    r = runner.invoke(main, ["add", name, "--scope", scope], input=value)
    assert r.exit_code == 0, r.output


def test_add_list_show_never_leak_value(vault_env: Path) -> None:
    runner = CliRunner()
    _init_and_add(runner, "ANTHROPIC_API_KEY", "global", "sk-top-secret")

    r = runner.invoke(main, ["list"])
    assert r.exit_code == 0
    assert "sk-top-secret" not in r.output
    assert "ANTHROPIC_API_KEY" in r.output

    r = runner.invoke(main, ["show", "ANTHROPIC_API_KEY", "--scope", "global"])
    assert r.exit_code == 0
    assert "sk-top-secret" not in r.output


def test_reveal_requires_confirmation(vault_env: Path) -> None:
    runner = CliRunner()
    _init_and_add(runner, "TEST_KEY", "global", "my-secret")

    # Declined: should not print value.
    r = runner.invoke(main, ["reveal", "TEST_KEY"], input="n\n")
    assert "my-secret" not in r.output

    # Confirmed with --yes: prints value.
    r = runner.invoke(main, ["reveal", "TEST_KEY", "--yes"])
    assert r.exit_code == 0
    assert "my-secret" in r.output


def test_agent_status_is_json(vault_env: Path) -> None:
    runner = CliRunner()
    r = runner.invoke(main, ["init"])
    assert r.exit_code == 0
    r = runner.invoke(main, ["agent", "status"])
    assert r.exit_code == 0
    data = json.loads(r.output.strip().splitlines()[-1])
    assert data["exists"] is True


def test_agent_list_names_never_contains_values(vault_env: Path) -> None:
    runner = CliRunner()
    _init_and_add(runner, "ANTHROPIC_API_KEY", "global", "sk-very-secret")
    r = runner.invoke(main, ["agent", "list-names"])
    assert r.exit_code == 0
    assert "sk-very-secret" not in r.output
    data = json.loads(r.output.strip().splitlines()[-1])
    assert any(item["name"] == "ANTHROPIC_API_KEY" for item in data)
    for item in data:
        assert "value" not in item


def test_agent_inject_writes_env_and_never_echoes_value(vault_env: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    _init_and_add(runner, "ANTHROPIC_API_KEY", "global", "sk-super-secret")
    project = tmp_path / "proj"
    project.mkdir()
    (project / "app.py").write_text('os.getenv("ANTHROPIC_API_KEY")\n')

    r = runner.invoke(
        main,
        ["agent", "inject", str(project), "--env", "dev", "--project-name", "proj"],
    )
    assert r.exit_code == 0, r.output
    assert "sk-super-secret" not in r.output
    env_text = (project / ".env").read_text()
    assert "ANTHROPIC_API_KEY=sk-super-secret" in env_text

    # JSON output includes written names but not values.
    data = json.loads(r.output.strip().splitlines()[-1])
    assert "ANTHROPIC_API_KEY" in data["written"]


def test_audit_log_records_operations(vault_env: Path) -> None:
    runner = CliRunner()
    _init_and_add(runner, "TEST_KEY", "global", "v")
    runner.invoke(main, ["list"])
    runner.invoke(main, ["show", "TEST_KEY"])
    r = runner.invoke(main, ["audit", "--json"])
    assert r.exit_code == 0
    lines = [ln for ln in r.output.strip().splitlines() if ln]
    ops = [json.loads(ln)["op"] for ln in lines]
    assert "init" in ops
    assert "add" in ops
    assert "list" in ops
    assert "show" in ops


def test_reveal_rejects_invalid_name(vault_env: Path) -> None:
    runner = CliRunner()
    runner.invoke(main, ["init"])
    r = runner.invoke(main, ["reveal", "lowercase"])
    assert r.exit_code != 0
    assert r.exception is not None
    assert "Invalid secret name" in str(r.exception)


def test_copy_rejects_invalid_scope(vault_env: Path) -> None:
    runner = CliRunner()
    runner.invoke(main, ["init"])
    r = runner.invoke(main, ["copy", "TEST_KEY", "--scope", "bad-scope"])
    assert r.exit_code != 0
    assert r.exception is not None
    assert "Invalid scope" in str(r.exception)


def test_revoke_rejects_invalid_name(vault_env: Path) -> None:
    runner = CliRunner()
    runner.invoke(main, ["init"])
    r = runner.invoke(main, ["revoke", "bad-name"])
    assert r.exit_code != 0
    assert r.exception is not None
    assert "Invalid secret name" in str(r.exception)
