from __future__ import annotations

from pathlib import Path

from vibe_secrets.envwriter import write_env
from vibe_secrets.resolver import resolve
from vibe_secrets.vault import Vault


def _setup_vault() -> Vault:
    v = Vault()
    v.init_empty()
    v.add("ANTHROPIC_API_KEY", "global", "sk-global")
    v.add("SUPABASE_URL", "project:saleson:dev", "https://example.supabase.co")
    return v


def test_preserve_creates_file_with_header(tmp_path: Path, vault_env: Path) -> None:
    v = _setup_vault()
    project = tmp_path / "saleson"
    project.mkdir()
    names = ["ANTHROPIC_API_KEY", "SUPABASE_URL"]
    res = resolve(v, names, "saleson", "dev")
    out = write_env(project, ".env", res)
    text = (project / ".env").read_text()
    assert text.startswith("# Managed by vibe-secrets")
    assert "ANTHROPIC_API_KEY=sk-global" in text
    assert "SUPABASE_URL=" in text
    assert set(out["written"].keys()) == {"ANTHROPIC_API_KEY", "SUPABASE_URL"}


def test_preserve_skips_existing(tmp_path: Path, vault_env: Path) -> None:
    v = _setup_vault()
    project = tmp_path / "p"
    project.mkdir()
    (project / ".env").write_text("# Managed by vibe-secrets\nANTHROPIC_API_KEY=existing-value\n")
    res = resolve(v, ["ANTHROPIC_API_KEY", "SUPABASE_URL"], "saleson", "dev")
    out = write_env(project, ".env", res, overwrite=False)
    text = (project / ".env").read_text()
    assert "ANTHROPIC_API_KEY=existing-value" in text
    assert "SUPABASE_URL=" in text
    assert "ANTHROPIC_API_KEY" in out["skipped"]
    assert "SUPABASE_URL" in out["written"]


def test_overwrite_replaces_existing(tmp_path: Path, vault_env: Path) -> None:
    v = _setup_vault()
    project = tmp_path / "p"
    project.mkdir()
    (project / ".env").write_text("# Managed by vibe-secrets\nANTHROPIC_API_KEY=old-value\n")
    res = resolve(v, ["ANTHROPIC_API_KEY"], "saleson", "dev")
    out = write_env(project, ".env", res, overwrite=True)
    text = (project / ".env").read_text()
    assert "ANTHROPIC_API_KEY=sk-global" in text
    assert "old-value" not in text
    assert "ANTHROPIC_API_KEY" in out["overwrote"]


def test_missing_and_revoked_are_reported(tmp_path: Path, vault_env: Path) -> None:
    v = _setup_vault()
    v.add("OLDKEY", "global", "x")
    v.revoke("OLDKEY", "global")
    project = tmp_path / "p"
    project.mkdir()
    res = resolve(v, ["ANTHROPIC_API_KEY", "OLDKEY", "NOWHERE_KEY"], "saleson", "dev")
    out = write_env(project, ".env", res)
    assert out["missing"] == ["NOWHERE_KEY"]
    assert out["revoked"] == ["OLDKEY"]
    assert "ANTHROPIC_API_KEY" in out["written"]
    text = (project / ".env").read_text()
    assert "OLDKEY" not in text
    assert "NOWHERE_KEY" not in text


def test_values_with_special_characters_are_quoted(tmp_path: Path, vault_env: Path) -> None:
    v = Vault()
    v.init_empty()
    v.add("WEIRD", "global", 'a b"c$d')
    project = tmp_path / "p"
    project.mkdir()
    res = resolve(v, ["WEIRD"], None, None)
    write_env(project, ".env", res)
    text = (project / ".env").read_text()
    assert 'WEIRD="a b\\"c\\$d"' in text


def test_preserves_comments_and_order_in_preserve_mode(tmp_path: Path, vault_env: Path) -> None:
    v = _setup_vault()
    project = tmp_path / "p"
    project.mkdir()
    (project / ".env").write_text("# Managed by vibe-secrets\n# user comment\nEXISTING_VAR=abc\n")
    res = resolve(v, ["ANTHROPIC_API_KEY"], "saleson", "dev")
    write_env(project, ".env", res)
    text = (project / ".env").read_text()
    assert "# user comment" in text
    assert "EXISTING_VAR=abc" in text
    assert "ANTHROPIC_API_KEY=sk-global" in text
