# vibe-secrets dev & install tasks.
# Run `just` (no args) to list available tasks.

default:
    @just --list

# ---------- global install (pipx) ----------

# Install vibe-secrets globally for this user (via pipx, recommended).
install:
    pipx install --force .

# Install in editable mode (local changes take effect without reinstall).
install-dev:
    pipx install --force --editable .

# Remove the global install.
uninstall:
    pipx uninstall vibe-secrets || true

# One-shot new-machine setup: install + create vault + install Claude skill.
# Add a project path to also onboard a project in the same step:
#     just onboard ~/projects/myapp
onboard project="":
    just install
    vibe-secrets bootstrap {{project}}

# ---------- local dev ----------

# Create venv and install with dev deps.
dev:
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -e ".[dev]"

# Run the test suite.
test:
    .venv/bin/python -m pytest

# Run tests with coverage.
cover:
    .venv/bin/python -m pytest --cov=vibe_secrets --cov-report=term-missing

# Lint with ruff.
lint:
    .venv/bin/ruff check src tests

# Auto-format with ruff.
format:
    .venv/bin/ruff format src tests
    .venv/bin/ruff check --fix src tests

# All checks: lint + tests. Use this before committing.
check: lint test

# Remove build artifacts and caches.
clean:
    rm -rf build dist *.egg-info .pytest_cache .coverage htmlcov .ruff_cache
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Regenerate claude/skills/vibe-secrets/SKILL.md from the Python templates.
# Run this whenever templates.py changes so the repo's reference copy stays in sync.
regen-skill:
    .venv/bin/python -c "from vibe_secrets import templates; print(templates.claude_skill_md(), end='')" > claude/skills/vibe-secrets/SKILL.md

# ---------- packaging ----------

# Build sdist + wheel.
build:
    .venv/bin/pip install --quiet build
    .venv/bin/python -m build
