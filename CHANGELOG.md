# Changelog

All notable changes to **vibe-secrets** are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] — 2026-04-21

### Fixed

- `envwriter._shell_quote` now correctly escapes `\n` and `\t` inside double-quoted
  `.env` values, preventing broken multi-line `.env` files.
- `projectops.parse_env_file` now unescapes `\\n`, `\\t`, `\\"`, and `\\\\` inside
  double-quoted values during import, so round-trips through the vault preserve
  special characters.
- `KeyRecord.from_storage` now ignores unknown fields instead of crashing with
  `TypeError`, making vault data forward-compatible with future format versions.
- `registry.save` now writes atomically via tempfile + `os.replace`, preventing
  corruption of `projects.json` if the process is interrupted.
- `scanner` now emits a `UserWarning` when the 20,000-file safety limit is hit,
  instead of silently truncating results.
- CLI commands `reveal`, `copy`, and `revoke` now validate secret names and scopes
  up front, giving clear errors instead of generic "Not found" messages.

## [0.1.0] — 2026-04-20

First public release.

### Added

- Local encrypted vault using Fernet (AES-128-CBC + HMAC-SHA256).
- 256-bit master key stored in the OS keychain (macOS Keychain, Linux Secret
  Service, Windows Credential Manager). Overridable via `VIBE_SECRETS_MASTER`
  for tests.
- Scoped overlay resolution: `project:<name>:<env>` → `global`.
- Human CLI: `init`, `status`, `add`, `list`, `search`, `show`, `reveal`,
  `copy`, `rotate`, `revoke`, `delete`, `scan`, `inject`, `audit`, `tui`, `help`.
- Project operations: `setup`, `import`, `sync`, `diff`, `fanout`, `projects`.
- Agent-safe commands (value-blind, JSON output): `agent status`,
  `agent list-names`, `agent scan`, `agent inject`, `agent diff`, `agent sync`,
  `agent setup`, `agent fanout`, `agent projects`.
- Cross-agent rules emission: `AGENTS.md`, `CLAUDE.md`, Cursor (`.cursor/rules/vibe-secrets.mdc`),
  GitHub Copilot (`.github/copilot-instructions.md`), Windsurf (`.windsurfrules`).
  Auto-detected based on directory/file presence, or explicitly via `--emit`.
- User-level Claude Code skill installer (`skill install`, `skill uninstall`,
  `skill status`); overridable via `CLAUDE_SKILLS_HOME`.
- `bootstrap` — one-shot onboarding on a new machine (master + vault +
  Claude skill + optional project setup).
- Encrypted backup and restore with a user-supplied passphrase
  (`backup` / `restore`); the backup is portable across machines.
- Master-key rotation with re-encryption (`reset-master`).
- Shell completion emission for bash / zsh / fish (`completion show`).
- Append-only local audit log with JSONL output.
- Textual TUI matching the concept wireframe: scope tree, key details, audit tail.
- Env-var scanner covering Python, TS/JS, Go, Rust, Ruby, Dart, Swift, Kotlin,
  Java, PHP, shell, YAML/TOML/INI, JSON, `.env*`.
- Justfile with install / dev / test / cover / lint / format / build tasks.
- Ruff config and formatting baseline.
- 82+ tests.

### Security

- Tamper-detection verified (bit-flipped ciphertext is rejected).
- Agent interface never returns raw values.
- Confirmation required for `reveal`, `copy`, `rotate` (with value-prompt),
  `revoke`, `delete`, `reset-master`, `restore`.
- File permissions: files `0o600`, directories `0o700`.

[Unreleased]: https://github.com/moinsen-dev/vibe-secrets/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/moinsen-dev/vibe-secrets/releases/tag/v0.1.0
