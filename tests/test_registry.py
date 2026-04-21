from __future__ import annotations

from pathlib import Path

from vibe_secrets import registry


def test_register_persists_metadata(vault_env: Path, tmp_path: Path) -> None:
    p = tmp_path / "demo"
    p.mkdir()
    registry.register(p, "demo", "dev")
    entry = registry.get(p)
    assert entry is not None
    assert entry["name"] == "demo"
    assert entry["default_env"] == "dev"


def test_record_inject_accumulates_keys(vault_env: Path, tmp_path: Path) -> None:
    p = tmp_path / "demo"
    p.mkdir()
    registry.register(p, "demo", "dev")
    registry.record_inject(p, "demo", "dev", ["A_KEY", "B_KEY"])
    registry.record_inject(p, "demo", "dev", ["B_KEY", "C_KEY"])
    registry.record_inject(p, "demo", "prod", ["P_KEY"])
    entry = registry.get(p)
    assert entry is not None
    assert entry["keys"]["dev"] == ["A_KEY", "B_KEY", "C_KEY"]
    assert entry["keys"]["prod"] == ["P_KEY"]


def test_projects_using_returns_all_matches(vault_env: Path, tmp_path: Path) -> None:
    a = tmp_path / "a"
    a.mkdir()
    b = tmp_path / "b"
    b.mkdir()
    registry.register(a, "a", "dev")
    registry.register(b, "b", "dev")
    registry.record_inject(a, "a", "dev", ["SHARED_KEY", "A_ONLY"])
    registry.record_inject(b, "b", "prod", ["SHARED_KEY"])
    result = registry.projects_using("SHARED_KEY")
    paths = {r[0] for r in result}
    assert paths == {str(a.resolve()), str(b.resolve())}
    assert {r[2] for r in result} == {"dev", "prod"}


def test_unregister(vault_env: Path, tmp_path: Path) -> None:
    p = tmp_path / "demo"
    p.mkdir()
    registry.register(p, "demo", "dev")
    assert registry.unregister(p) is True
    assert registry.get(p) is None
    assert registry.unregister(p) is False


def test_registry_file_has_restricted_permissions(vault_env: Path, tmp_path: Path) -> None:
    p = tmp_path / "demo"
    p.mkdir()
    registry.register(p, "demo", "dev")
    from vibe_secrets.config import vault_dir

    reg_path = vault_dir() / "projects.json"
    assert reg_path.exists()
    mode = reg_path.stat().st_mode & 0o777
    assert mode == 0o600
