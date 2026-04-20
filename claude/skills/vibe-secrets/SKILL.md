---
name: vibe-secrets
description: Use vibe-secrets (local encrypted vault) to populate .env files and manage API keys in a project. Trigger when the user mentions a missing env var, asks to set up a new project with keys, asks how to rotate/inject secrets, when you see an .env.example but no .env, or when a script fails because of a missing ANTHROPIC_API_KEY / OPENAI_API_KEY / DATABASE_URL / similar env var in a project that has a .vault.yaml.
---

# vibe-secrets — agent rules

A project with a `.vault.yaml` uses **vibe-secrets**, a local encrypted
secret vault. The user's API keys live in the vault, not in their project.
Your job is to populate `.env` files through the vault without ever
handling raw values yourself.

**Do:**

- Populate `.env` with `vibe-secrets agent inject . --env <env>`.
  The vault writes values directly to disk. You receive only `ok`/`missing`.
- Discover referenced names with `vibe-secrets agent scan .`.
- List available names (without values) with `vibe-secrets agent list-names`.
- Check vault readiness with `vibe-secrets agent status`.

**Never:**

- Never ask the user to paste an API key into chat.
- Never echo a raw value from `.env`, the vault, or tool output.
- Never `cat .env`, `echo $SOMEKEY`, or otherwise print secrets.
- Never offer to add a key on the user's behalf — they must add it themselves
  so the raw value never passes through you.

**If a key is missing**, instruct the user:

```
vibe-secrets add NAME --scope global
# or for a project-specific override:
vibe-secrets add NAME --scope project:<name>:<env>
```

**If a key is revoked**, tell the user to `vibe-secrets rotate NAME --scope <scope>`.

**After the user rotates a global key**, suggest `vibe-secrets agent fanout NAME`
to re-inject into every project that used it.

**Before running build/test steps that depend on env vars**, verify alignment with
`vibe-secrets agent diff . --env <env>` (structural only — no values emitted).

## Onboarding a project with no `.vault.yaml`

Run `vibe-secrets agent setup <path>` — writes `.vault.yaml`, updates
`AGENTS.md` / `CLAUDE.md` with a rules block, and adds `.env*` to
`.gitignore`. Does not read any secret values.

## Commands

| Command | Purpose |
|---|---|
| `vibe-secrets agent status` | vault readiness |
| `vibe-secrets agent list-names [--scope S]` | names + metadata |
| `vibe-secrets agent scan <path>` | names referenced in project |
| `vibe-secrets agent inject <path> [--env E]` | write/update `.env` |
| `vibe-secrets agent diff <path> [--env E]` | structural diff vs vault |
| `vibe-secrets agent sync <path> [--env E]` | scan + inject + register |
| `vibe-secrets agent setup <path>` | onboard a project |
| `vibe-secrets agent fanout NAME` | re-inject after rotation |
| `vibe-secrets agent projects` | registered projects |

**Human-only** (do not call; instruct the user to run them):

- `vibe-secrets init`, `add`, `rotate`, `reveal`, `copy`, `revoke`, `delete`

All of these touch raw values or are destructive.
