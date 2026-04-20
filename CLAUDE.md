# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build / test / lint

Everything routes through the Justfile.

- `just dev` — create `.venv/` and install `-e ".[dev]"`. Do this once.
- `just test` — run the full suite (currently 93 tests).
- `just lint` — `ruff check`. Must be clean (zero errors) before committing.
- `just format` — `ruff format` then `ruff check --fix`.
- `just check` — `lint` + `test`. The pre-commit gate.
- `just regen-skill` — **must run after editing `templates.py`** (see below).
- `just build` — build sdist+wheel. `just install` — install globally via pipx.

Running a single test:
```bash
.venv/bin/python -m pytest tests/test_vault.py::test_encryption_at_rest
```

## Architectural invariants

These span multiple files and are not obvious from reading any one of them.

### Raw secret values never leave the tool through an API surface

The only code path that writes a value out is `envwriter.write_env()` — and only
to a file path the user supplied. Everywhere else:

- `agent` CLI subcommands return only names, statuses, paths — never values.
- `reveal` / `copy` require confirmation (or `--yes`).
- TUI masks values by default; revealing requires a modal confirmation.
- `agent.log()` in `audit.py` never persists values, only key names + actor +
  op.
- Adding a new code path that returns a value is a breaking change to the trust
  model — do not do it without explicit sign-off.

### `templates.py` is the single source of truth for every rules document

All agent-rules text (Claude skill, AGENTS.md, CLAUDE.md, Cursor .mdc, Copilot,
Windsurf) is rendered from functions in `src/vibe_secrets/templates.py`. Do NOT
hand-edit `claude/skills/vibe-secrets/SKILL.md` — after changing `templates.py`
run `just regen-skill` and commit both files together. Tests in
`tests/test_installer.py` pin the content contract.

### Scope resolution has a subtle "revoked blocks fallback" rule

`resolver.resolve()` — if a project-scoped record exists but is `revoked`, we
return `source="revoked"` and do NOT fall back to `global`. The user's intent
was clearly to override the global key; a revoked override must not silently
fall through. The test `test_revoked_project_blocks_fallback` locks this.

### Paths are functions, not module-level constants

`config.vault_dir()`, `config.vault_file()`, `config.audit_file()` are called at
runtime so tests can redirect via `VIBE_SECRETS_HOME`. Same pattern for
`installer.claude_skill_dir()` / `CLAUDE_SKILLS_HOME`. If you introduce a new
path, follow this pattern or the tests will pick up the developer's real home.

### Scanner must be given `exclude=` when run against its own `.env`

`scanner.scan(project, exclude=[env_path])` — otherwise `diff` and `sync`
re-discover keys from the target `.env` file they're comparing against, leading
to empty `only_in_env` reports. Always pass the target file when scanning from
`projectops`.

### Two storage layers

- `vault.enc` — encrypted secrets, Fernet-encrypted, managed by `vault.py`.
- `projects.json` — plain metadata registry of paths ↔ project names ↔
  keys-per-env. Managed by `registry.py`. Contains NO secret values. Every
  inject updates both. Registry is what makes `fanout` possible; if you add
  a new code path that writes `.env`, wire it through `record_inject`.

### Master-key test environment

Tests NEVER touch the OS keychain. The `vault_env` fixture in
`tests/conftest.py` sets both `VIBE_SECRETS_HOME` (to a tmp dir) and
`VIBE_SECRETS_MASTER` (to a fresh random Fernet key). All tests that need a
vault should take the `vault_env` parameter. `keystore._override()` checks
`VIBE_SECRETS_MASTER` first.

### Marker-delimited block updates are idempotent

Files like `AGENTS.md`, `CLAUDE.md`, `copilot-instructions.md`, `.windsurfrules`
use `<!-- vibe-secrets:begin -->` / `end` markers. `projectops._upsert_block()`
rewrites the block in place on re-run — never appends duplicates. Cursor
(`.cursor/rules/vibe-secrets.mdc`) is different: we own the whole file because
Cursor expects a single frontmatter block per `.mdc`. `_write_cursor_rule`
handles that case.

### Ruff per-file exceptions

- `src/vibe_secrets/cli.py` — `B904` disabled (Click translates exceptions at
  the CLI boundary; `from e` noise isn't useful there).
- `src/vibe_secrets/tui.py` — `RUF012`, `UP045` disabled (Textual framework
  expects `BINDINGS = [...]` as a class-level list and `ModalScreen[Optional[T]]`).

If you're tempted to add a new ignore, consider fixing the code instead.

## Where things live

- `cli.py` — every user-facing command. Agent-safe subcommands are under `agent`.
- `vault.py` — encrypted store + `reset_master`.
- `projectops.py` — setup / import / sync / diff / fanout. All multi-file
  orchestration of project-level ops lives here.
- `installer.py` — user-level Claude Code skill install (`~/.claude/skills/`).
- `backup.py` — portable encrypted backup (passphrase-based, not keychain-bound).
- `registry.py` — plain-JSON project registry.
- `scanner.py` — env-var name discovery. Conservative; stopwords filtered.
- `envwriter.py` — `.env` merge policy (preserve default, overwrite opt-in).
- `tui.py` — Textual UI. Matches the wireframe in `concept/wireframe.md`.
- `concept/` — original PRD + ASCII wireframe from the ideation phase.
  Still the contract for the product surface; check here before changing UX.

## Release / publish

Publishing to PyPI is not yet wired (see GitHub issue #3 for CI that includes
trusted-publisher publish). Versioning: single-sourced in `pyproject.toml`
`version = "X.Y.Z"` and mirrored in `CHANGELOG.md` on release. Tag with `vX.Y.Z`.

## Open issues worth knowing about

- [#1](https://github.com/moinsen-dev/vibe-secrets/issues/1) monorepo / sub-project support
- [#2](https://github.com/moinsen-dev/vibe-secrets/issues/2) hardcoded-secret finder in source
- [#3](https://github.com/moinsen-dev/vibe-secrets/issues/3) CI pipeline

## When the user asks you to extend the tool

- New subcommand that touches values: put it in `cli.py` only, never in
  `agent`. Add confirmation. Audit-log it.
- New agent subcommand: must emit JSON, must be value-blind, must log as
  `agent.<name>`.
- New emit target (another agent assistant's rules file): add a renderer to
  `templates.py`, wire into `projectops.EMIT_TARGETS` + `setup_project`, and
  auto-detect on directory/file presence where sensible.
- New env scanner pattern: add to `scanner._PATTERNS`, ensure it has exactly
  one capture group for the name, add a test in `tests/test_scanner.py`.
