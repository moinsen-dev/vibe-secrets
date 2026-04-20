# Claude Code skill for vibe-secrets

Drops `vibe-secrets` into Claude Code's skill system so the assistant knows
how to use the vault and, critically, **never handles raw secret values**.

## Install

Copy the skill into Claude Code's user-level skills directory:

```bash
mkdir -p ~/.claude/skills/vibe-secrets
cp claude/skills/vibe-secrets/SKILL.md ~/.claude/skills/vibe-secrets/
```

Or symlink it (recommended — you pick up updates when you `git pull`):

```bash
ln -s "$(pwd)/claude/skills/vibe-secrets" ~/.claude/skills/vibe-secrets
```

Restart Claude Code. The skill becomes available to every project that
mentions `.env`, a `.vault.yaml`, or a missing env var.

## What it does

The skill is a rule set, not a hook. When Claude Code's description
matching fires it on a conversation, Claude reads the skill body, follows
the rules, and uses only the safe `vibe-secrets agent …` subcommands.

Key guarantees the skill enforces:

- Claude must never ask the user to paste an API key into chat.
- Claude must never echo a raw value from `.env`, the vault, or tool output.
- Claude must never `cat .env`, `echo $VAR`, or similar.
- Claude must use `vibe-secrets agent inject` to populate `.env` — the
  vault writes values, Claude only sees `ok / missing / revoked`.

## Commands the skill teaches

Agent-safe (no values ever emitted):

- `vibe-secrets agent status`
- `vibe-secrets agent list-names`
- `vibe-secrets agent scan <project>`
- `vibe-secrets agent inject <project> --env dev`
- `vibe-secrets agent diff <project> --env dev`
- `vibe-secrets agent sync <project>`
- `vibe-secrets agent setup <project>`
- `vibe-secrets agent fanout NAME`
- `vibe-secrets agent projects`

Human-only (the skill tells Claude to direct the user to run these):

- `vibe-secrets init`, `add`, `rotate`, `reveal`, `copy`, `revoke`, `delete`
