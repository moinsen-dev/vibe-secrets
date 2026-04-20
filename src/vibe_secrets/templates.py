"""Canonical agent-rules templates.

One source of truth for every rules document vibe-secrets writes:
- Claude Code user-level skill  (installed via `vibe-secrets skill install`)
- Per-project AGENTS.md         (setup)
- Per-project CLAUDE.md         (setup)
- Per-project .cursor/rules/vibe-secrets.mdc (setup, auto-detected or --emit cursor)
- Per-project .github/copilot-instructions.md (setup, --emit copilot)
- Per-project .windsurfrules   (setup, --emit windsurf)
"""

from __future__ import annotations

BEGIN_MARKER = "<!-- vibe-secrets:begin -->"
END_MARKER = "<!-- vibe-secrets:end -->"


# Core behavior rules — identical across every target.
# Kept self-contained: no project-specific placeholders.
RULES_CORE = """\
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
"""


SAFE_COMMANDS_TABLE = """\
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
"""


def _project_suffix(project_name: str, env: str) -> str:
    return (
        "\n**Project identity**\n\n"
        f"- `project_name` in vault: `{project_name}` (see `.vault.yaml`)\n"
        f"- Default env: `{env}`\n"
    )


# ---------- per-project blocks (marker-delimited, idempotent) ----------


def agents_block(project_name: str, env: str) -> str:
    return (
        f"{BEGIN_MARKER}\n\n"
        "## Secrets — vibe-secrets\n\n"
        "This project uses **vibe-secrets**, a local encrypted vault, for API keys.\n"
        "Agents MUST follow these rules.\n\n"
        f"{RULES_CORE}\n"
        f"{_project_suffix(project_name, env)}\n"
        f"{END_MARKER}\n"
    )


def claude_md_block(project_name: str, env: str) -> str:
    return (
        f"{BEGIN_MARKER}\n\n"
        "## Secrets\n\n"
        "This project uses **vibe-secrets** for API keys. See `AGENTS.md` →\n"
        "*Secrets — vibe-secrets* for the full rules Claude must follow.\n\n"
        "Populate `.env` with:\n\n"
        "```\n"
        f"vibe-secrets agent inject . --env {env}\n"
        "```\n\n"
        "Never ask the user to paste raw API keys into chat. Never echo values.\n"
        f"Project name: `{project_name}` (see `.vault.yaml`).\n\n"
        f"{END_MARKER}\n"
    )


def cursor_mdc(project_name: str, env: str) -> str:
    """Cursor project rule — YAML frontmatter + markdown body."""
    return (
        "---\n"
        "description: vibe-secrets — local encrypted secret vault; never handle raw API keys directly\n"
        "alwaysApply: true\n"
        "---\n\n"
        "# Secrets — vibe-secrets\n\n"
        "This project uses **vibe-secrets**, a local encrypted vault, for API keys.\n"
        "Agents MUST follow these rules.\n\n"
        f"{RULES_CORE}\n"
        f"{_project_suffix(project_name, env)}"
    )


def copilot_block(project_name: str, env: str) -> str:
    return (
        f"{BEGIN_MARKER}\n\n"
        "## Secrets — vibe-secrets\n\n"
        "This project uses **vibe-secrets**, a local encrypted vault, for API keys.\n"
        "Agents MUST follow these rules.\n\n"
        f"{RULES_CORE}\n"
        f"{_project_suffix(project_name, env)}\n"
        f"{END_MARKER}\n"
    )


def windsurf_block(project_name: str, env: str) -> str:
    return copilot_block(project_name, env)


# ---------- user-level Claude Code skill ----------

CLAUDE_SKILL_FRONTMATTER = (
    "---\n"
    "name: vibe-secrets\n"
    "description: Use vibe-secrets (local encrypted vault) to populate .env files and manage API keys in a project. "
    "Trigger when the user mentions a missing env var, asks to set up a new project with keys, asks how to rotate/inject secrets, "
    "when you see an .env.example but no .env, or when a script fails because of a missing ANTHROPIC_API_KEY / OPENAI_API_KEY / "
    "DATABASE_URL / similar env var in a project that has a .vault.yaml.\n"
    "---\n"
)


def claude_skill_md() -> str:
    """Full SKILL.md body — installed into ~/.claude/skills/vibe-secrets/SKILL.md."""
    return (
        f"{CLAUDE_SKILL_FRONTMATTER}\n"
        "# vibe-secrets — agent rules\n\n"
        "A project with a `.vault.yaml` uses **vibe-secrets**, a local encrypted\n"
        "secret vault. The user's API keys live in the vault, not in their project.\n"
        "Your job is to populate `.env` files through the vault without ever\n"
        "handling raw values yourself.\n\n"
        f"{RULES_CORE}\n"
        "## Onboarding a project with no `.vault.yaml`\n\n"
        "Run `vibe-secrets agent setup <path>` — writes `.vault.yaml`, updates\n"
        "`AGENTS.md` / `CLAUDE.md` with a rules block, and adds `.env*` to\n"
        "`.gitignore`. Does not read any secret values.\n\n"
        "## Commands\n\n"
        f"{SAFE_COMMANDS_TABLE}"
    )
