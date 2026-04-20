from __future__ import annotations

from pathlib import Path

from vibe_secrets import projectops, registry
from vibe_secrets.projectops import ImportDecision
from vibe_secrets.vault import Vault

# ---------- setup ----------


def test_setup_creates_files_and_registers(tmp_path: Path, vault_env: Path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    projectops.setup_project(project, "demo", "dev")

    assert (project / ".vault.yaml").exists()
    assert (project / "AGENTS.md").exists()
    assert (project / "CLAUDE.md").exists()
    assert (project / ".gitignore").exists()

    agents = (project / "AGENTS.md").read_text()
    assert "vibe-secrets:begin" in agents
    assert "vibe-secrets:end" in agents
    assert "demo" in agents
    assert "Never ask the user to paste" in agents

    gi = (project / ".gitignore").read_text()
    assert ".env" in gi
    assert ".env.*" in gi
    assert "!.env.example" in gi
    assert ".vault.lock" in gi

    reg_entry = registry.get(project)
    assert reg_entry is not None
    assert reg_entry["name"] == "demo"


def test_setup_is_idempotent(tmp_path: Path, vault_env: Path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    projectops.setup_project(project, "demo", "dev")
    before = (project / "AGENTS.md").read_text()
    projectops.setup_project(project, "demo", "dev")
    after = (project / "AGENTS.md").read_text()
    # Block count stays at exactly one.
    assert after.count("vibe-secrets:begin") == 1
    assert after.count("vibe-secrets:end") == 1
    assert before == after


def test_setup_appends_block_to_existing_agents_md(tmp_path: Path, vault_env: Path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    (project / "AGENTS.md").write_text("# Agents\n\nExisting content.\n")
    projectops.setup_project(project, "demo", "dev")
    text = (project / "AGENTS.md").read_text()
    assert "Existing content." in text
    assert "vibe-secrets:begin" in text


def test_setup_updates_existing_block(tmp_path: Path, vault_env: Path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    projectops.setup_project(project, "demo", "dev")
    projectops.setup_project(project, "demo-renamed", "prod")
    text = (project / "AGENTS.md").read_text()
    assert "demo-renamed" in text
    assert "prod" in text
    assert text.count("vibe-secrets:begin") == 1


def test_setup_preserves_existing_gitignore_entries(tmp_path: Path, vault_env: Path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    (project / ".gitignore").write_text("# my ignores\nnode_modules/\n")
    projectops.setup_project(project, "demo", "dev")
    text = (project / ".gitignore").read_text()
    assert "node_modules/" in text
    assert ".env" in text


# ---------- import helpers ----------


def test_parse_env_file_handles_quotes_and_export(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    p.write_text(
        "# a comment\n"
        "FOO=bar\n"
        'QUOTED="hello world"\n'
        "SINGLE='value'\n"
        "export PATHY=/tmp/x\n"
        "BLANK=\n"
    )
    out = dict(projectops.parse_env_file(p))
    assert out["FOO"] == "bar"
    assert out["QUOTED"] == "hello world"
    assert out["SINGLE"] == "value"
    assert out["PATHY"] == "/tmp/x"
    assert out["BLANK"] == ""


def test_is_managed_detects_header(tmp_path: Path) -> None:
    p = tmp_path / ".env"
    p.write_text("# Managed by vibe-secrets. Do not commit.\nFOO=bar\n")
    assert projectops.is_managed(p) is True
    p.write_text("FOO=bar\n")
    assert projectops.is_managed(p) is False


def test_suggest_scope_from_filename() -> None:
    assert projectops.suggest_scope(".env", "demo") == "global"
    assert projectops.suggest_scope(".env.local", "demo") == "project:demo:dev"
    assert projectops.suggest_scope(".env.development", "demo") == "project:demo:dev"
    assert projectops.suggest_scope(".env.production", "demo") == "project:demo:prod"
    assert projectops.suggest_scope(".env.test", "demo") == "project:demo:test"


def test_collect_import_candidates_skips_managed(tmp_path: Path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    (project / ".env").write_text("# Managed by vibe-secrets. Do not commit.\nFOO=bar\n")
    (project / ".env.local").write_text("BAZ=qux\n")
    found = projectops.collect_import_candidates(project)
    # Only unmanaged files appear.
    names = [p.name for p, _ in found]
    assert names == [".env.local"]
    # Include managed explicitly.
    found2 = projectops.collect_import_candidates(project, include_managed=True)
    names2 = sorted(p.name for p, _ in found2)
    assert names2 == [".env", ".env.local"]


def test_apply_import_adds_rotates_and_skips(tmp_path: Path, vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    v.add("EXISTING_KEY", "global", "old-value")

    decisions = [
        ImportDecision("NEW_KEY", "global", "add", "/dev/null"),
        ImportDecision("EXISTING_KEY", "global", "rotate", "/dev/null"),
        ImportDecision("SKIP_ME", "global", "skip", "/dev/null"),
    ]
    values = {
        ("/dev/null", "NEW_KEY"): "new-val",
        ("/dev/null", "EXISTING_KEY"): "updated-val",
        ("/dev/null", "SKIP_ME"): "unused",
    }
    out = projectops.apply_import(v, decisions, values)
    assert ("NEW_KEY", "global") in out["added"]
    assert ("EXISTING_KEY", "global") in out["rotated"]
    assert any(n == "SKIP_ME" and reason == "user-skipped" for n, _, reason in out["skipped"])

    assert v.get("NEW_KEY", "global").value == "new-val"
    assert v.get("EXISTING_KEY", "global").value == "updated-val"


# ---------- sync / diff ----------


def test_diff_match_differ_and_only(tmp_path: Path, vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    v.add("ANTHROPIC_API_KEY", "global", "sk-a")
    v.add("SUPABASE_URL", "project:demo:dev", "https://x.supabase.co")

    project = tmp_path / "demo"
    project.mkdir()
    (project / "app.py").write_text(
        'os.getenv("ANTHROPIC_API_KEY")\nos.getenv("SUPABASE_URL")\nos.getenv("GHOST_KEY")\n'
    )
    (project / ".env").write_text(
        "# Managed by vibe-secrets\n"
        "ANTHROPIC_API_KEY=sk-a\n"
        "SUPABASE_URL=wrong-value\n"
        "EXTRA_VAR=whatever\n"
    )
    report = projectops.diff_project(v, project, "demo", "dev")
    pub = report.to_public()
    assert "ANTHROPIC_API_KEY" in pub["match"]
    assert "SUPABASE_URL" in pub["differ"]
    assert "GHOST_KEY" in pub["missing_in_vault"]
    assert "EXTRA_VAR" in pub["only_in_env"]


def test_sync_writes_and_updates_registry(tmp_path: Path, vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    v.add("ANTHROPIC_API_KEY", "global", "sk-a")

    project = tmp_path / "demo"
    project.mkdir()
    (project / "app.py").write_text('os.getenv("ANTHROPIC_API_KEY")\n')
    result = projectops.sync_project(v, project, "demo", "dev")
    assert result["written"] == ["ANTHROPIC_API_KEY"]
    env_text = (project / ".env").read_text()
    assert "ANTHROPIC_API_KEY=sk-a" in env_text

    entry = registry.get(project)
    assert entry is not None
    assert "ANTHROPIC_API_KEY" in entry["keys"]["dev"]


# ---------- fanout ----------


def test_fanout_reinjects_into_registered_projects(tmp_path: Path, vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    v.add("ANTHROPIC_API_KEY", "global", "sk-old")

    a = tmp_path / "a"
    a.mkdir()
    (a / "app.py").write_text('os.getenv("ANTHROPIC_API_KEY")\n')
    projectops.sync_project(v, a, "a", "dev")

    b = tmp_path / "b"
    b.mkdir()
    (b / "app.py").write_text('os.getenv("ANTHROPIC_API_KEY")\n')
    projectops.sync_project(v, b, "b", "dev")

    # Rotate the global key, then fan out.
    v.rotate("ANTHROPIC_API_KEY", "global", "sk-NEW")
    results = projectops.fanout_key(v, "ANTHROPIC_API_KEY")
    paths = {r["path"] for r in results}
    assert paths == {str(a.resolve()), str(b.resolve())}

    for proj in (a, b):
        text = (proj / ".env").read_text()
        assert "ANTHROPIC_API_KEY=sk-NEW" in text
        assert "sk-old" not in text


def test_fanout_reports_unavailable_for_missing_key(tmp_path: Path, vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    a = tmp_path / "a"
    a.mkdir()
    registry.register(a, "a", "dev")
    registry.record_inject(a, "a", "dev", ["GHOST_KEY"])
    results = projectops.fanout_key(v, "GHOST_KEY")
    assert results[0]["status"] == "unavailable"
