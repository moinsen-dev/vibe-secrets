# Wireframe — vibe-secrets (Vault Manager, main screen)

## ASCII

```
+----------------------------------------------------+
| vibe-secrets       [scope: all v]      [locked ^]  |
+------------------+---------------------------------+
| [SCOPE TREE]     | [KEY DETAILS]                   |
|                  |                                 |
| global           | Name:   ANTHROPIC_API_KEY       |
|  ANTHROPIC_KEY   | Scope:  global                  |
|  OPENAI_KEY      | Added:  2026-04-14              |
|  GMAPS_KEY       | Used:   3 projects              |
|                  | Last:   14 min ago              |
| proj:saleson     | Status: active                  |
|  dev/            |                                 |
|   SUPABASE_URL   | Value:  ••••••••••  [reveal]    |
|   SUPABASE_KEY   |                                 |
|  prod/           | [ Copy ]  [ Rotate ]  [ Revoke ]|
|   SUPABASE_URL   |                                 |
|                  | [ Inject into project... ]      |
| proj:cargovox    |                                 |
|  dev/            |                                 |
|   MAPBOX_TOKEN   |                                 |
+------------------+---------------------------------+
| [AUDIT] 14:02 inject saleson:dev ANTHROPIC_KEY ok  |
+----------------------------------------------------+

Legend:
- SCOPE TREE: groups of keys — global + per-project (dev/prod).
- KEY DETAILS: metadata of the selected key; value masked, reveal requires local unlock.
- Actions: Copy (to clipboard, confirms), Rotate (new value, old marked revoked), Revoke (invalidate now).
- Inject into project: picks a target folder + env → writes the key into its .env.
- AUDIT: tail of the local access log — who/what/when.
```

## Image prompt

```
Image prompt:
"A clean, minimal desktop terminal-UI (TUI) window for a local secret vault called 'vibe-secrets', monospace font, dark slate background with soft cyan and amber accents. Left column: a collapsible scope tree with one 'global' group and two 'project:<name>' groups, each expanding into 'dev/' and 'prod/' folders with short uppercase key names like ANTHROPIC_API_KEY and SUPABASE_URL. Right column: a key detail panel showing Name, Scope, Added, Used-by, Last-access, Status, and a masked value field with a small 'reveal' button, followed by three flat action buttons 'Copy', 'Rotate', 'Revoke' and a wider 'Inject into project...' button. Top bar shows the app name, a scope filter dropdown, and a small padlock indicator. Bottom bar shows a single line audit tail. Calm, security-tool aesthetic, no brand logos, no decorative illustrations, flat modern design, crisp 1px borders."
```
