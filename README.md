# vibe-secrets

Local encrypted secret vault for a solo developer working across many
AI-integrated projects. One place for every API key. Coding agents populate
`.env` files **without ever seeing the raw values**.

## Why

You have 30 side projects. Each needs `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
maybe `GOOGLE_MAPS_KEY`, sometimes a project-specific Supabase URL. Copying
keys between folders leaks them into shell history, chat context, and stale
`.env` files. Rotation across projects is a nightmare.

`vibe-secrets` solves that, locally.

## Design

- **Local-first.** No network. No cloud sync. No telemetry.
- **Encrypted at rest.** Fernet (AES-128-CBC + HMAC-SHA256) with a 256-bit
  master key.
- **Master key in the OS keychain.** Never written to disk by this tool.
- **Scoped overlay.** Resolution order: `project:<name>:<env>` → `global`.
- **Agent-safe.** The `agent` subcommands never return raw values — they
  write `.env` on disk at a path you choose and report only
  `ok / missing / revoked / skipped`.
- **Append-only audit log** of every read, inject, rotation.
- **Cross-agent.** Emits rules for AGENTS.md, CLAUDE.md, Cursor, Copilot,
  Windsurf.
- **Small.** One CLI binary, one TUI, one installable Claude Code skill.

## Install

### Quickest — global user install via pipx

```bash
pipx install .                     # from a clone
# or:
pipx install vibe-secrets          # once published to PyPI
```

### With the Justfile

```bash
just install          # pipx install --force .
just install-dev      # editable, for hacking on vibe-secrets itself
just onboard          # install + bootstrap (vault + Claude skill)
```

### For development

```bash
just dev              # create .venv and install with dev deps
just test             # run the suite (76 tests)
```

## New machine, zero to useful in one command

```bash
vibe-secrets bootstrap
```

Creates the vault (master key in the OS keychain), installs the Claude Code
skill into `~/.claude/skills/vibe-secrets/`, and prints next steps. Add a
project path to also onboard it in the same call:

```bash
vibe-secrets bootstrap ~/projects/myapp
```

Then add a key the user-only way (the value is prompted, never echoed):

```bash
vibe-secrets add ANTHROPIC_API_KEY --scope global
```

## Typical flows

### Greenfield — new project

```bash
cd ~/projects/newapp
vibe-secrets setup .                        # writes .vault.yaml + rules + .gitignore
# … write code that references env vars …
vibe-secrets sync .                         # scan code, resolve from vault, write .env
```

### Brownfield — existing project with `.env` files

```bash
cd ~/projects/oldapp
vibe-secrets setup .
vibe-secrets import .                       # per-key prompts: which scope?
# (or non-interactive:)
vibe-secrets import . --yes \
  --default-scope "project:oldapp:dev" \
  --on-conflict rotate
vibe-secrets sync .                         # .env now written from the vault
```

### Rotation across every project that uses a key

```bash
vibe-secrets rotate ANTHROPIC_API_KEY --scope global
vibe-secrets fanout ANTHROPIC_API_KEY       # re-inject into every registered project
```

### Drift check without exposing values

```bash
vibe-secrets diff .                         # match / differ / missing / revoked / only_in_env
```

## Cross-agent rules

`setup` writes onboarding rules for any assistant whose directory it finds.
Auto-detected:

| Target | Path | Trigger |
|---|---|---|
| AGENTS.md | project root | always |
| CLAUDE.md | project root | always |
| Cursor | `.cursor/rules/vibe-secrets.mdc` | `.cursor/` exists |
| Copilot | `.github/copilot-instructions.md` | `.github/` exists |
| Windsurf | `.windsurfrules` | `.windsurfrules` exists |

Force a specific set:

```bash
vibe-secrets setup . --emit agents,cursor,copilot
vibe-secrets setup . --emit all
```

Each target uses marker-delimited blocks (`<!-- vibe-secrets:begin -->` /
`end`) and is fully idempotent — re-running `setup` updates the block in
place rather than duplicating.

## Claude Code skill

```bash
vibe-secrets skill install          # → ~/.claude/skills/vibe-secrets/SKILL.md
vibe-secrets skill status
vibe-secrets skill uninstall
```

The skill teaches Claude to use the vault correctly: never ask the user to
paste API keys, never echo values, always use `vibe-secrets agent inject`
to populate `.env`. Source of truth lives in
`src/vibe_secrets/templates.py`.

## Agent mode

AI agents call the `agent` subcommands. Every one of them emits JSON with no
secret values. Set `VIBE_SECRETS_ACTOR=claude-code` (or `codex`, `cursor`,
etc.) so the audit log attributes correctly.

```bash
vibe-secrets agent status                     # { "exists": true, "has_master": true, … }
vibe-secrets agent list-names [--scope S]     # [{"name":…, "scope":…, "status":…}, …]
vibe-secrets agent scan <path>                # ["ANTHROPIC_API_KEY", …]
vibe-secrets agent inject <path> [--env E]    # writes .env, returns summary (no values)
vibe-secrets agent diff <path> [--env E]      # structural only; no values
vibe-secrets agent sync <path> [--env E]      # scan + inject + update registry
vibe-secrets agent setup <path>               # onboard a project
vibe-secrets agent fanout NAME                # re-inject after rotation
vibe-secrets agent projects                   # list registered projects
```

## Full CLI reference

### Lifecycle

| Command | Purpose |
|---|---|
| `init` | Create the vault file + master key (stored in OS keychain) |
| `status` | Vault path, existence, record counts |
| `bootstrap [PROJECT]` | New-machine one-shot: init + install skill + optional setup |
| `tui` | Launch the interactive vault manager |
| `help` | Show the quickstart card |

### Key operations

| Command | Purpose |
|---|---|
| `add NAME [--scope S]` | Add a secret (value via stdin or prompt) |
| `list [--scope S]` | List secrets (metadata only) |
| `search PATTERN` | Glob-match names across all scopes |
| `show NAME [--scope S]` | Metadata for one key (never the value) |
| `reveal NAME [--scope S]` | Print the raw value — requires confirmation |
| `copy NAME [--scope S]` | Copy the value to OS clipboard |
| `rotate NAME [--scope S]` | Replace the value |
| `revoke NAME [--scope S]` | Mark revoked (kept for metadata history) |
| `delete NAME [--scope S]` | Hard-delete; irreversible |

### Project operations

| Command | Purpose |
|---|---|
| `setup PATH [--emit …]` | Onboard: `.vault.yaml` + rules + `.gitignore` + register |
| `import PATH` | Read existing `.env*` files into the vault (interactive) |
| `scan PATH` | Discover env-var names referenced in a project |
| `inject PATH [--env E]` | Resolve + write `.env` (lower-level than `sync`) |
| `sync PATH [--env E]` | scan + resolve + inject + update registry (overwrite by default) |
| `diff PATH [--env E]` | Structural comparison `.env` vs vault — never prints values |
| `fanout NAME` | Re-inject NAME into every registered project that uses it |
| `projects` | List registered projects |

### Integration (user-level)

| Command | Purpose |
|---|---|
| `skill install [--force]` | Drop Claude Code skill into `~/.claude/skills/` |
| `skill uninstall` | Remove it |
| `skill status` | Report installation state |

### Audit

| Command | Purpose |
|---|---|
| `audit [--limit N] [--json]` | Tail the local audit log |

### Scopes

- `global` — available to every project unless overridden
- `project:<name>:<env>` — `<env>` is a free string, typically `dev` / `prod` / `test`

## Storage layout

```
~/.vibe-secrets/
├── vault.enc           # encrypted JSON of records (0600)
├── projects.json       # plain registry: paths ↔ names ↔ keys-per-env
└── audit.log           # append-only JSONL
```

Override the directory with `VIBE_SECRETS_HOME`. Override the Claude skills
directory with `CLAUDE_SKILLS_HOME`. Declare the actor in audit entries with
`VIBE_SECRETS_ACTOR`.

## Security model

- Master key: `cryptography.fernet` 256-bit key, stored in the OS keychain
  (macOS Keychain, Linux Secret Service, Windows Credential Manager). For
  automated tests only, set `VIBE_SECRETS_MASTER` to a base64 Fernet key to
  bypass the keyring.
- Vault at rest: encrypted with Fernet (AES-128-CBC for confidentiality,
  HMAC-SHA256 for integrity). Any bit flip is detected — we have a test for
  it.
- File permissions: all vault-owned files are `0o600`, directories `0o700`.
- Value exfiltration: `reveal` and `copy` require interactive confirmation
  (or `--yes`). `agent` commands never emit values through any code path.
- Tamper detection: modifying `vault.enc` out of band makes the next read
  fail with `VaultError`.
- Audit: every read, inject, rotation is appended to `audit.log` with
  timestamp, actor, op, key, scope, project.

## Non-goals

- Not a team secret manager. No sharing, no sync.
- Not a password manager for humans.
- Not a cloud KMS replacement.
- Not a code-scanner — `scan` only finds env-var names, not the values.

## Project structure

```
src/vibe_secrets/
├── config.py       runtime paths
├── models.py       KeyRecord + scope/name validation
├── keystore.py     OS-keychain master management
├── vault.py        encrypted store, atomic writes
├── audit.py        append-only JSONL log
├── resolver.py     overlay scope resolution
├── scanner.py      env-var name discovery
├── envwriter.py    .env merge (preserve / overwrite)
├── registry.py     plain-JSON project registry
├── projectops.py   setup / import / sync / diff / fanout
├── templates.py    agent rules (single source of truth)
├── installer.py    Claude Code skill install
├── clipboard.py    pbcopy / xclip / wl-copy / clip
├── cli.py          click CLI
└── tui.py          Textual TUI

claude/skills/vibe-secrets/SKILL.md  # regenerated from templates.py
tests/               76 tests total
```

## License

MIT
