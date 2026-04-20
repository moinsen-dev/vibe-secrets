# PRD — vibe-secrets

## 1. Problem
Solo developers working across many AI-integrated projects constantly copy API keys between folders by hand. This leaks keys into shell history, chat context, and stale `.env` files, and makes rotation and revocation painful.

## 2. Context
Used on a single developer's machine across a large tree of side projects, experiments, and client repos. Each project already uses AI coding agents (Claude Code, Codex, Gemini, ...) that need keys for services like Anthropic, OpenAI, Google Maps, Supabase, Mapbox, etc.

## 3. Vision
A local, encrypted secret vault with a CLI, a minimal TUI, and an agent bridge — so keys live in exactly one place, and coding agents can populate per-project `.env` files without ever seeing the raw values.

## 4. User Value
- One place for every API key the developer owns.
- Coding agents populate `.env` without handling raw values.
- Cheap rotation and revocation across every project at once.
- Per-project dev/prod isolation with a global fallback.
- Full audit trail of what was read by whom and when.

## 5. Actors
- **Developer (human):** manages keys through CLI/TUI, unlocks the vault, rotates/revokes.
- **AI coding agent:** discovers required key names in a project, asks the vault to inject them, reads only metadata and `ok` acks.

## 6. Core System Behavior
1. Developer adds a secret to a scope (`global` or `project:<name>:<env>`).
2. In a project, the AI agent scans code for referenced env-var names.
3. AI calls `vault inject --project <path> --env dev` with the needed names.
4. Vault resolves each name (project scope → global), writes values into `./.env`.
5. AI receives per-key `ok`/`missing` results — never values.
6. Every read and inject is appended to the local audit log.

## 7. Primary Screens / Surfaces
- **CLI:** `vault add|list|search|show|inject|rotate|revoke|delete|scan|unlock|lock`.
- **TUI (Vault Manager):** scope tree, key detail, inject action, audit tail.
- **Agent bridge:** local CLI / MCP endpoint callable by AI agents.
- **Project config:** `.vault.yaml` (optional) or annotated `AGENTS.md` / `CLAUDE.md` block naming the project and declared keys.

## 8. Features (Epics)
- **Vault core**
  - Encrypted local store (at rest + master unlock via OS keychain).
  - Scoped records: `global`, `project:<name>:<env>`.
  - Metadata: created, last-used, used-by-projects, status (active/revoked).
- **Key operations**
  - Add, show (metadata only by default), reveal (requires unlock + confirm).
  - Search and glob by name across scopes.
  - Rotate (new value, old marked revoked, audit linked).
  - Revoke/invalidate and hard-delete.
- **Project integration**
  - `scan <project>` — list env-var names referenced in project code.
  - `inject <project>` — write resolved values into `./.env` (create/update/merge).
  - Resolution overlay: project-scope first, then global.
- **Agent interface**
  - Agent-safe commands: list-names, scan, inject, status — never expose values.
  - Claude Code plugin shipped via marketplace; generic CLI for other agents.
- **Safety & audit**
  - Append-only audit log (time, actor, op, key, scope, project, result).
  - Confirmation prompts for reveal/rotate/delete.
  - `lock` command to drop the master from memory.

## 9. Inputs
- Developer-entered secret values (from CLI/TUI only).
- Project path(s) and declared project name.
- Scanned env-var names from project source files.
- Agent requests (structured calls: names + target project).

## 10. Outputs
- Populated `.env` files in target project folders.
- Metadata responses to agents (never raw values).
- Audit log entries.
- Optional per-project `.vault.lock` noting which keys were last injected.

## 11. Constraints
- Local-first. No network. No cloud sync. No telemetry.
- AI agents must never receive raw secret values over any interface.
- Encrypted at rest; master unlocked only via OS keychain or explicit passphrase.
- Not a team vault. Not a password manager. Not a code-scanner beyond env-name discovery.
- Small tool — a flat CLI, a simple TUI, a thin plugin. No server, no GUI app, no DB engine.

## 12. Open Questions (implementation-level only)
- Encryption primitive: `age`, `libsodium`, or OS-native (macOS Keychain items + file wrapper).
- Storage format: single encrypted file vs. per-key files.
- Agent transport: plain CLI subprocess vs. MCP server vs. both.
- How to fingerprint a project: folder path, git remote, or declared name in config file — or all three, in that priority.
- `.env` merge policy when target file already contains the key: overwrite, preserve, or prompt.
