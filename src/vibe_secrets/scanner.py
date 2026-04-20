"""Scans a project directory for referenced env-var names.

Read-only, pattern-based, conservative. Never interprets or executes code.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path

_NAME = r"[A-Z][A-Z0-9_]{1,}"


# Each pattern has exactly one capture group holding the env-var name.
_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"process\.env\.(" + _NAME + r")\b"),
    re.compile(r"process\.env\[['\"](" + _NAME + r")['\"]\]"),
    re.compile(r"import\.meta\.env\.(" + _NAME + r")\b"),
    re.compile(r"os\.getenv\(\s*['\"](" + _NAME + r")['\"]"),
    re.compile(r"os\.environ\s*\[\s*['\"](" + _NAME + r")['\"]"),
    re.compile(r"os\.environ\.get\(\s*['\"](" + _NAME + r")['\"]"),
    re.compile(r"ENV\s*\[\s*['\"](" + _NAME + r")['\"]"),
    re.compile(r"std::env::var\(\s*['\"](" + _NAME + r")['\"]"),
    re.compile(r"dotenv\.env\[\s*['\"](" + _NAME + r")['\"]"),
    re.compile(r"Platform\.environment\[\s*['\"](" + _NAME + r")['\"]"),
    re.compile(r"System\.getenv\(\s*['\"](" + _NAME + r")['\"]"),
    re.compile(r"getenv\(\s*['\"](" + _NAME + r")['\"]"),
    re.compile(r"\$\{(" + _NAME + r")\}"),
    re.compile(r"(?<![A-Za-z0-9_])\$(" + _NAME + r")\b"),
    # .env / shell "KEY=..." declarations
    re.compile(r"^\s*(?:export\s+)?(" + _NAME + r")\s*=", re.MULTILINE),
]


_INCLUDE_EXT = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".go",
    ".rs",
    ".rb",
    ".dart",
    ".swift",
    ".kt",
    ".java",
    ".scala",
    ".sh",
    ".bash",
    ".zsh",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".json",
    ".env",
    ".php",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
}

_EXTRA_NAMES = {
    ".env",
    ".env.example",
    ".env.local",
    ".env.development",
    ".env.production",
    ".env.dev",
    ".env.prod",
    ".env.sample",
    ".env.test",
}

_EXCLUDE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "dist",
    "build",
    ".next",
    ".nuxt",
    ".cache",
    "target",
    "vendor",
    "Pods",
    ".dart_tool",
    ".gradle",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "coverage",
    "htmlcov",
}

# Words that look like env-var names but almost never are.
_STOPWORDS = {
    "TRUE",
    "FALSE",
    "NULL",
    "NONE",
    "NAN",
    "TODO",
    "FIXME",
    "XXX",
    "NOTE",
    "ERROR",
    "WARN",
    "WARNING",
    "INFO",
    "DEBUG",
    "TRACE",
    "GET",
    "POST",
    "PUT",
    "DELETE",
    "PATCH",
    "HEAD",
    "OK",
    "OKAY",
    "README",
    "LICENSE",
    "CHANGELOG",
}

_MAX_FILE_BYTES = 512 * 1024  # 512 KiB per file


def _iter_files(root: Path, max_files: int = 20000) -> Iterable[Path]:
    root = root.resolve()
    count = 0
    for dirpath, dirs, files in os.walk(root):
        # Prune excluded dirs in-place.
        dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS and not d.startswith(".git")]
        for fn in files:
            if fn in _EXTRA_NAMES or fn.startswith(".env"):
                p = Path(dirpath) / fn
            else:
                suffix = Path(fn).suffix.lower()
                if suffix not in _INCLUDE_EXT:
                    continue
                p = Path(dirpath) / fn
            count += 1
            if count > max_files:
                return
            yield p


def scan(
    project_path: Path | str,
    exclude: Iterable[Path] | None = None,
) -> set[str]:
    root = Path(project_path)
    if not root.exists():
        raise FileNotFoundError(root)
    skip: set[Path] = set()
    if exclude:
        for e in exclude:
            try:
                skip.add(Path(e).resolve())
            except OSError:
                pass
    found: set[str] = set()
    for p in _iter_files(root):
        try:
            if p.resolve() in skip:
                continue
            if p.stat().st_size > _MAX_FILE_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue
        for pat in _PATTERNS:
            for m in pat.finditer(text):
                name = m.group(1)
                if not name or len(name) < 3:
                    continue
                if name in _STOPWORDS:
                    continue
                if name.startswith("HTTP_") and len(name) <= 8:
                    continue
                found.add(name)
    return found
