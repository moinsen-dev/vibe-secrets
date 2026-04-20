# Concept ledger — vibe-secrets

- **Actor(s):** Solo developer juggling many AI-integrated projects on one machine, using multiple coding agents (Claude Code, Codex, Gemini, ...).
- **Primary object:** Local encrypted secret vault, scoped as `global` + `project:<name>:<env>` (dev/prod).
- **Core behavior:** AI agent discovers required secret names inside a project → requests the vault to inject them → vault writes values directly into `./.env` (or equivalent). AI only ever sees `ok` + metadata.
- **Primary output:** `.env` files populated in each project folder; audit events.
- **Boundary / non-goals:**
  - Single user, single machine — not a team secret manager.
  - No cloud sync, no remote backend.
  - Not a password manager for humans.
  - AI agents can never read raw secret values — only enumerate names.

## Other captured facts

- **Operations:** add, list, search by name, show metadata, inject into project, rotate, revoke/invalidate, delete.
- **Project identity:** absolute folder path; optional human name declared in `AGENTS.md` / `CLAUDE.md` / `.vault.yaml`.
- **Scope resolution:** overlay — `project:<name>:<env>` takes precedence, falls back to `global`.
- **Surface:** CLI + local TUI for the human, plus a Claude Code plugin (marketplace) / MCP bridge for agents.
- **Trust model:** encrypted at rest (age or libsodium), master unlocked via OS keychain, audit log of every read/inject, no outbound network.
- **AI scan helper:** AI can glob a project's code for referenced env-var names to know what to request — reading code, not values.
