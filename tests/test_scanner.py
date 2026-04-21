from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from vibe_secrets import scanner
from vibe_secrets.scanner import scan


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_node_style(tmp_path: Path) -> None:
    _write(
        tmp_path / "app.ts",
        "const k = process.env.ANTHROPIC_API_KEY;\n"
        'const s = process.env["SUPABASE_URL"];\n'
        "const m = import.meta.env.VITE_MAPBOX_TOKEN;\n",
    )
    found = scan(tmp_path)
    assert "ANTHROPIC_API_KEY" in found
    assert "SUPABASE_URL" in found
    assert "VITE_MAPBOX_TOKEN" in found


def test_python_style(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.py",
        "import os\n"
        'a = os.getenv("OPENAI_API_KEY")\n'
        'b = os.environ["DATABASE_URL"]\n'
        'c = os.environ.get("SENTRY_DSN")\n',
    )
    found = scan(tmp_path)
    assert {"OPENAI_API_KEY", "DATABASE_URL", "SENTRY_DSN"}.issubset(found)


def test_dotenv_declarations(tmp_path: Path) -> None:
    _write(
        tmp_path / ".env.example",
        "# sample\n"
        "ANTHROPIC_API_KEY=\n"
        "export GOOGLE_MAPS_KEY=\n"
        "SUPABASE_URL=https://x.supabase.co\n",
    )
    found = scan(tmp_path)
    assert {"ANTHROPIC_API_KEY", "GOOGLE_MAPS_KEY", "SUPABASE_URL"}.issubset(found)


def test_dart_and_shell(tmp_path: Path) -> None:
    _write(
        tmp_path / "lib" / "env.dart",
        'final a = Platform.environment["ANTHROPIC_API_KEY"]!;\n',
    )
    _write(
        tmp_path / "deploy.sh",
        "#!/bin/bash\necho $MAPBOX_TOKEN\necho ${GOOGLE_MAPS_KEY}\n",
    )
    found = scan(tmp_path)
    assert "ANTHROPIC_API_KEY" in found
    assert "MAPBOX_TOKEN" in found
    assert "GOOGLE_MAPS_KEY" in found


def test_excludes_node_modules_and_venv(tmp_path: Path) -> None:
    _write(
        tmp_path / "node_modules" / "pkg" / "index.js",
        "process.env.SHOULD_NOT_APPEAR;\n",
    )
    _write(
        tmp_path / ".venv" / "lib" / "site.py",
        'os.getenv("ALSO_NOT_APPEAR")\n',
    )
    _write(tmp_path / "src" / "app.py", 'os.getenv("VISIBLE_ONE")\n')
    found = scan(tmp_path)
    assert "VISIBLE_ONE" in found
    assert "SHOULD_NOT_APPEAR" not in found
    assert "ALSO_NOT_APPEAR" not in found


def test_stopwords_filtered(tmp_path: Path) -> None:
    _write(
        tmp_path / "x.py",
        'if DEBUG:\n    print("TODO")\na = os.getenv("REAL_KEY")\n',
    )
    found = scan(tmp_path)
    assert "REAL_KEY" in found
    assert "DEBUG" not in found
    assert "TODO" not in found


def test_min_length(tmp_path: Path) -> None:
    _write(tmp_path / "a.py", 'os.getenv("AB")\nos.getenv("ABC")\n')
    found = scan(tmp_path)
    assert "AB" not in found
    assert "ABC" in found


def test_scan_warns_on_truncation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for i in range(10):
        _write(tmp_path / f"f{i}.py", f'os.getenv("KEY{i}")\n')

    orig_iter = scanner._iter_files

    def limited_iter(root, max_files=20000):
        return orig_iter(root, max_files=3)

    monkeypatch.setattr(scanner, "_iter_files", limited_iter)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = scan(tmp_path)
        assert len(w) == 1
        assert "Scanning stopped" in str(w[0].message)
        assert issubclass(w[0].category, UserWarning)
        # Some keys should still have been found before the limit.
        assert len(result) >= 1
