"""Human CLI for vibe-secrets.

All commands that touch secret values (reveal, copy, rotate, delete) require
explicit confirmation unless --yes is passed. Raw values are never echoed
except by `reveal` (confirmation-gated) and `copy` (sent to clipboard only).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from . import __version__, envwriter, installer, projectops, scanner
from . import audit as audit_mod
from . import clipboard as clip
from . import registry as registry_mod
from . import resolver as resolver_mod
from .keystore import KeystoreError, create_master, has_master
from .models import (
    GLOBAL_SCOPE,
    validate_name,
    validate_scope,
)
from .projectops import ImportDecision
from .vault import AlreadyExists, NotFound, Vault, VaultError

console = Console(highlight=False, soft_wrap=True)
err_console = Console(stderr=True, highlight=False, soft_wrap=True)


# ---------- shared helpers ----------


def _open_vault() -> Vault:
    v = Vault()
    if not v.exists():
        raise click.ClickException("No vault found. Run `vibe-secrets init` first.")
    return v


def _read_value_interactively() -> str:
    if not sys.stdin.isatty():
        value = sys.stdin.read()
        # allow trailing newline
        if value.endswith("\n"):
            value = value[:-1]
        return value
    return click.prompt("Value", hide_input=True, confirmation_prompt=False)


def _confirm(prompt: str, yes: bool) -> bool:
    if yes:
        return True
    return click.confirm(prompt, default=False)


def _read_project_name(project: Path) -> str:
    # Optional name from .vault.yaml or fallback to folder basename.
    candidate = project / ".vault.yaml"
    if candidate.exists():
        try:
            import yaml  # type: ignore[import-untyped]

            data = yaml.safe_load(candidate.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("project"), str):
                return data["project"].strip()
        except Exception:
            pass
    return project.name


# ---------- root group ----------

QUICKSTART = """\
[bold cyan]vibe-secrets[/bold cyan] — local encrypted secret vault for AI-assisted development

[bold]First time on this machine?[/bold]
  [cyan]vibe-secrets bootstrap[/cyan]                        create vault + install Claude Code skill
  [cyan]vibe-secrets bootstrap ~/projects/myapp[/cyan]       \u2026and onboard a project in one step

[bold]Day-to-day[/bold]
  [cyan]vibe-secrets status[/cyan]                           vault health
  [cyan]vibe-secrets add NAME [--scope SCOPE][/cyan]         add a secret (value prompted, never echoed)
  [cyan]vibe-secrets setup .[/cyan]                          onboard this project (rules + .gitignore)
  [cyan]vibe-secrets import .[/cyan]                         pull existing .env* files into the vault
  [cyan]vibe-secrets sync .[/cyan]                           write .env from the vault
  [cyan]vibe-secrets diff .[/cyan]                           structural check — no values printed
  [cyan]vibe-secrets rotate NAME[/cyan] then [cyan]vibe-secrets fanout NAME[/cyan]  rotate across every project

[bold]For AI agents (safe, value-blind)[/bold]
  [cyan]vibe-secrets agent inject . --env dev[/cyan]         populate .env; raw values never returned
  [cyan]vibe-secrets agent status | scan | diff | sync | setup | fanout | projects[/cyan]
  [cyan]vibe-secrets skill install[/cyan]                    drop Claude Code skill into ~/.claude/skills/

[bold]Discovery[/bold]
  [cyan]vibe-secrets --help[/cyan]                           full command reference
  [cyan]vibe-secrets <command> --help[/cyan]                 per-command options

[dim]Local-only. Encrypted at rest (Fernet: AES-128-CBC + HMAC-SHA256).
Master key stored in the OS keychain. AI agents never see raw values.[/dim]
"""


def _print_quickstart() -> None:
    console.print(QUICKSTART)


@click.group(invoke_without_command=True)
@click.version_option(__version__, prog_name="vibe-secrets")
@click.pass_context
def main(ctx: click.Context) -> None:
    """vibe-secrets — local encrypted secret vault for AI-assisted development."""
    if ctx.invoked_subcommand is None:
        _print_quickstart()


@main.command()
def help() -> None:
    """Show the quickstart card. Use `--help` for the full reference."""
    _print_quickstart()


# ---------- lifecycle ----------


@main.command()
def init() -> None:
    """Create the vault file and master key (stored in the OS keychain)."""
    v = Vault()
    if v.exists():
        raise click.ClickException(f"Vault already exists at {v.path}")
    try:
        if not has_master():
            create_master()
            console.print("[green]Created new master key in OS keychain.[/green]")
        else:
            console.print("[yellow]Using existing master key from OS keychain.[/yellow]")
    except KeystoreError as e:
        raise click.ClickException(str(e))
    v.init_empty()
    audit_mod.log("init", path=str(v.path))
    console.print(f"[green]Vault initialized at[/green] {v.path}")


@main.command()
def status() -> None:
    """Show vault location, existence, and record counts."""
    v = Vault()
    info = v.stats()
    info["has_master"] = False
    try:
        info["has_master"] = has_master()
    except KeystoreError:
        info["has_master"] = False
    t = Table(show_header=False, box=None)
    t.add_row("Path", str(info["path"]))
    t.add_row("Exists", "yes" if info["exists"] else "no")
    t.add_row("Master key", "yes" if info["has_master"] else "no")
    if info["exists"]:
        t.add_row("Total records", str(info["total"]))
        t.add_row("Active", str(info["active"]))
        t.add_row("Revoked", str(info["revoked"]))
        t.add_row(
            "Scopes",
            ", ".join(f"{s} ({n})" for s, n in sorted(info["scopes"].items())) or "-",
        )
    console.print(t)


# ---------- core key ops ----------


@main.command()
@click.argument("name")
@click.option("--scope", default=GLOBAL_SCOPE, show_default=True)
@click.option("--value", default=None, help="Pass value inline (discouraged). Prefer stdin/prompt.")
def add(name: str, scope: str, value: str | None) -> None:
    """Add a new secret. Value read from stdin or prompted securely by default."""
    validate_name(name)
    validate_scope(scope)
    v = _open_vault()
    if value is None:
        value = _read_value_interactively()
    if value == "":
        raise click.ClickException("Value cannot be empty.")
    try:
        v.add(name, scope, value)
    except AlreadyExists as e:
        raise click.ClickException(str(e))
    except VaultError as e:
        raise click.ClickException(str(e))
    audit_mod.log("add", name=name, scope=scope)
    console.print(f"[green]Added[/green] {scope}/{name}")


@main.command(name="list")
@click.option("--scope", default=None, help="Filter to one scope.")
def list_cmd(scope: str | None) -> None:
    """List secrets (metadata only)."""
    v = _open_vault()
    if scope:
        validate_scope(scope)
    records = v.list(scope)
    if not records:
        console.print("[dim]No secrets.[/dim]")
        return
    t = Table(title="Secrets", show_lines=False)
    t.add_column("Scope", no_wrap=True)
    t.add_column("Name", no_wrap=True)
    t.add_column("Status")
    t.add_column("Created")
    t.add_column("Last used")
    for r in records:
        status_cell = "[green]active[/green]" if r.status == "active" else "[red]revoked[/red]"
        t.add_row(
            r.scope,
            r.name,
            status_cell,
            r.created_at,
            r.last_used_at or "-",
        )
    console.print(t)
    audit_mod.log("list", scope=scope, count=len(records))


@main.command()
@click.argument("pattern")
def search(pattern: str) -> None:
    """Glob-match secret names across all scopes (e.g. 'SUPABASE_*')."""
    v = _open_vault()
    records = v.search(pattern)
    if not records:
        console.print("[dim]No matches.[/dim]")
        return
    t = Table(show_header=True)
    t.add_column("Scope", no_wrap=True)
    t.add_column("Name", no_wrap=True)
    t.add_column("Status")
    for r in records:
        cell = "[green]active[/green]" if r.status == "active" else "[red]revoked[/red]"
        t.add_row(r.scope, r.name, cell)
    console.print(t)
    audit_mod.log("search", pattern=pattern, count=len(records))


@main.command()
@click.argument("name")
@click.option("--scope", default=GLOBAL_SCOPE, show_default=True)
def show(name: str, scope: str) -> None:
    """Show metadata for a secret (never the value)."""
    v = _open_vault()
    try:
        rec = v.get(name, scope)
    except NotFound:
        raise click.ClickException(f"Not found: {scope}/{name}")
    t = Table(show_header=False, box=None)
    for k, val in rec.to_public().items():
        t.add_row(k, str(val) if val is not None else "-")
    console.print(t)
    audit_mod.log("show", name=name, scope=scope)


@main.command()
@click.argument("name")
@click.option("--scope", default=GLOBAL_SCOPE, show_default=True)
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def reveal(name: str, scope: str, yes: bool) -> None:
    """Print the raw value. Requires confirmation."""
    v = _open_vault()
    try:
        rec = v.get(name, scope)
    except NotFound:
        raise click.ClickException(f"Not found: {scope}/{name}")
    if rec.status != "active":
        err_console.print(f"[red]Warning:[/red] {scope}/{name} is {rec.status}.")
    if not _confirm(f"Reveal raw value for {scope}/{name}?", yes):
        raise click.Abort()
    audit_mod.log("reveal", name=name, scope=scope)
    click.echo(rec.value)


@main.command()
@click.argument("name")
@click.option("--scope", default=GLOBAL_SCOPE, show_default=True)
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def copy(name: str, scope: str, yes: bool) -> None:
    """Copy the raw value to the OS clipboard."""
    v = _open_vault()
    try:
        rec = v.get(name, scope)
    except NotFound:
        raise click.ClickException(f"Not found: {scope}/{name}")
    if not _confirm(f"Copy {scope}/{name} value to clipboard?", yes):
        raise click.Abort()
    ok = clip.copy_to_clipboard(rec.value)
    audit_mod.log("copy", name=name, scope=scope, ok=ok)
    if ok:
        console.print(f"[green]Copied[/green] {scope}/{name} to clipboard.")
    else:
        raise click.ClickException("Clipboard tool not found (install pbcopy/xclip/wl-copy).")


@main.command()
@click.argument("name")
@click.option("--scope", default=GLOBAL_SCOPE, show_default=True)
@click.option("--value", default=None, help="Pass value inline (discouraged).")
def rotate(name: str, scope: str, value: str | None) -> None:
    """Replace the value of a secret. Old version is removed from active store."""
    v = _open_vault()
    try:
        v.get(name, scope)
    except NotFound:
        raise click.ClickException(f"Not found: {scope}/{name}")
    new_value = value if value is not None else _read_value_interactively()
    if new_value == "":
        raise click.ClickException("Value cannot be empty.")
    v.rotate(name, scope, new_value)
    audit_mod.log("rotate", name=name, scope=scope)
    console.print(f"[green]Rotated[/green] {scope}/{name}")


@main.command()
@click.argument("name")
@click.option("--scope", default=GLOBAL_SCOPE, show_default=True)
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def revoke(name: str, scope: str, yes: bool) -> None:
    """Mark a secret as revoked. It will be ignored by inject but metadata is kept."""
    v = _open_vault()
    try:
        v.get(name, scope)
    except NotFound:
        raise click.ClickException(f"Not found: {scope}/{name}")
    if not _confirm(f"Revoke {scope}/{name}?", yes):
        raise click.Abort()
    v.revoke(name, scope)
    audit_mod.log("revoke", name=name, scope=scope)
    console.print(f"[yellow]Revoked[/yellow] {scope}/{name}")


@main.command()
@click.argument("name")
@click.option("--scope", default=GLOBAL_SCOPE, show_default=True)
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def delete(name: str, scope: str, yes: bool) -> None:
    """Hard-delete a secret (metadata + value). Irreversible."""
    v = _open_vault()
    try:
        v.get(name, scope)
    except NotFound:
        raise click.ClickException(f"Not found: {scope}/{name}")
    if not _confirm(f"Permanently delete {scope}/{name}?", yes):
        raise click.Abort()
    v.delete(name, scope)
    audit_mod.log("delete", name=name, scope=scope)
    console.print(f"[red]Deleted[/red] {scope}/{name}")


# ---------- project ops ----------


@main.command()
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, resolve_path=True))
def scan(project_path: str) -> None:
    """List env-var names referenced in a project's source code."""
    project = Path(project_path)
    names = sorted(scanner.scan(project))
    if not names:
        console.print("[dim]No env-var names found.[/dim]")
        return
    for n in names:
        click.echo(n)
    audit_mod.log("scan", project=str(project), count=len(names))


@main.command()
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, resolve_path=True))
@click.option("--env", default="dev", show_default=True, help="Target env for scope lookup.")
@click.option(
    "--project-name",
    default=None,
    help="Override project name; defaults to folder name or .vault.yaml",
)
@click.option("--file", "env_file", default=".env", show_default=True, help="Target .env file.")
@click.option("--names", default=None, help="Comma-separated names. If omitted, scanner is used.")
@click.option("--overwrite", is_flag=True, help="Overwrite existing values in the target file.")
def inject(
    project_path: str,
    env: str,
    project_name: str | None,
    env_file: str,
    names: str | None,
    overwrite: bool,
) -> None:
    """Resolve keys for a project and write them into its .env file."""
    project = Path(project_path)
    pname = project_name or _read_project_name(project)
    if names:
        name_list = [n.strip() for n in names.split(",") if n.strip()]
    else:
        name_list = sorted(scanner.scan(project, exclude=[project / env_file]))
    if not name_list:
        console.print("[dim]Nothing to inject — no names found.[/dim]")
        return
    v = _open_vault()
    resolutions = resolver_mod.resolve(v, name_list, pname, env)
    result = envwriter.write_env(project, env_file, resolutions, overwrite=overwrite)

    for n, scope in result["written"].items():
        v.touch_used(n, scope, pname)
    if result["written"]:
        registry_mod.record_inject(project, pname, env, list(result["written"].keys()))

    audit_mod.log(
        "inject",
        project=str(project),
        project_name=pname,
        env=env,
        file=result["path"],
        written=list(result["written"].keys()),
        overwrote=list(result["overwrote"].keys()),
        skipped=list(result["skipped"].keys()),
        missing=result["missing"],
        revoked=result["revoked"],
    )

    t = Table(title=f"Injected → {result['path']}", show_lines=False)
    t.add_column("Name")
    t.add_column("Source")
    t.add_column("Status")
    for n in name_list:
        res = next((r for r in resolutions if r.name == n), None)
        src = res.source if res else "missing"
        if n in result["written"]:
            status_cell = (
                "[green]written[/green]"
                if n not in result["overwrote"]
                else "[green]overwrote[/green]"
            )
        elif n in result["skipped"]:
            status_cell = f"[yellow]skipped ({result['skipped'][n]})[/yellow]"
        elif n in result["missing"]:
            status_cell = "[red]missing[/red]"
        elif n in result["revoked"]:
            status_cell = "[red]revoked[/red]"
        else:
            status_cell = "-"
        t.add_row(n, src, status_cell)
    console.print(t)


@main.command()
@click.option("--limit", default=50, show_default=True, help="Max entries to show.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSONL.")
def audit(limit: int, as_json: bool) -> None:
    """Show the tail of the audit log."""
    entries = audit_mod.tail(limit)
    if as_json:
        for e in entries:
            click.echo(json.dumps(e, ensure_ascii=False))
        return
    if not entries:
        console.print("[dim]No audit events.[/dim]")
        return
    t = Table(show_lines=False)
    t.add_column("Time", no_wrap=True)
    t.add_column("Actor")
    t.add_column("Op")
    t.add_column("Details")
    for e in entries:
        details = ", ".join(f"{k}={v}" for k, v in e.items() if k not in ("ts", "op", "actor"))
        t.add_row(e.get("ts", "-"), e.get("actor", "-"), e.get("op", "-"), details)
    console.print(t)


# ---------- setup / import / sync / diff / fanout / projects ----------


@main.command()
@click.argument("project_path", type=click.Path(file_okay=False, resolve_path=True))
@click.option("--project-name", default=None, help="Name to register; defaults to folder name.")
@click.option("--env", default="dev", show_default=True, help="Default env for the project.")
@click.option(
    "--emit",
    "emit",
    multiple=True,
    help="Rules files to emit. Values: agents, claude, cursor, copilot, windsurf, all. "
    "Omit for auto-detect (agents + claude always; cursor if .cursor/, copilot if .github/, windsurf if .windsurfrules).",
)
def setup(
    project_path: str,
    project_name: str | None,
    env: str,
    emit: tuple[str, ...],
) -> None:
    """Onboard a project: write .vault.yaml, update agent rules files and .gitignore, register."""
    project = Path(project_path)
    project.mkdir(parents=True, exist_ok=True)
    try:
        result = projectops.setup_project(
            project, project_name, env, emit=list(emit) if emit else None
        )
    except ValueError as e:
        raise click.ClickException(str(e))
    audit_mod.log(
        "setup",
        project=result["project"],
        project_name=result["project_name"],
        env=result["default_env"],
        emits={k: v["status"] for k, v in result["emits"].items()},
        gitignore_added=result["gitignore"]["added"],
    )
    t = Table(show_header=False, box=None)
    t.add_row("Project", result["project"])
    t.add_row("Name", result["project_name"])
    t.add_row("Default env", result["default_env"])
    t.add_row(".vault.yaml", result["vault_yaml"])
    for target, info in result["emits"].items():
        t.add_row(f"{target}", f"{info['status']} → {info['path']}")
    added = result["gitignore"]["added"]
    t.add_row(".gitignore", ", ".join(added) if added else "up-to-date")
    console.print(t)


@main.command("import")
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, resolve_path=True))
@click.option(
    "--project-name",
    default=None,
    help="Override project name; defaults to folder name or .vault.yaml.",
)
@click.option(
    "--default-scope",
    default=None,
    help="Scope for keys whose file doesn't suggest one (e.g. 'global' or 'project:NAME:dev').",
)
@click.option(
    "--on-conflict",
    type=click.Choice(["skip", "rotate", "keep"]),
    default="skip",
    show_default=True,
    help="What to do when a name already exists in the chosen scope.",
)
@click.option(
    "--include-managed", is_flag=True, help="Also read .env files already managed by vibe-secrets."
)
@click.option(
    "--yes", is_flag=True, help="Non-interactive: accept suggested scopes without prompting."
)
def import_cmd(
    project_path: str,
    project_name: str | None,
    default_scope: str | None,
    on_conflict: str,
    include_managed: bool,
    yes: bool,
) -> None:
    """Import keys from a project's existing .env* files into the vault."""
    project = Path(project_path)
    pname = project_name or _read_project_name(project)
    v = _open_vault()
    candidates = projectops.collect_import_candidates(project, include_managed=include_managed)
    if not candidates:
        console.print("[dim]No .env files to import from.[/dim]")
        return

    decisions: list[ImportDecision] = []
    value_lookup: dict[tuple[str, str], str] = {}
    for path, entries in candidates:
        suggested = default_scope if default_scope else projectops.suggest_scope(path.name, pname)
        try:
            validate_scope(suggested)
        except ValueError as e:
            raise click.ClickException(str(e))

        console.print(f"\n[bold]{path}[/bold] → suggested scope: [cyan]{suggested}[/cyan]")
        for name, value in entries:
            fp = projectops.fingerprint(value) if value else "(empty)"
            chosen_scope = suggested
            action = "add"

            if not yes:
                console.print(f"  {name} [dim]({fp})[/dim]")
                raw_scope = click.prompt(
                    "    scope",
                    default=suggested,
                    show_default=True,
                )
                chosen_scope = raw_scope.strip() or suggested
                try:
                    validate_scope(chosen_scope)
                except ValueError as e:
                    console.print(f"    [red]{e}[/red] — skipped")
                    continue
                # Decide action based on collision.
                existing = v.try_get(name, chosen_scope)
                if existing is not None:
                    choice = click.prompt(
                        "    exists — [s]kip / [r]otate / [k]eep-vault",
                        default=on_conflict[0],
                        show_default=True,
                    )
                    c = choice.strip().lower()[:1]
                    if c == "s" or c == "k":
                        action = "skip"
                    elif c == "r":
                        action = "rotate"
                    else:
                        action = "skip"
                else:
                    action = "add"
            else:
                try:
                    validate_scope(chosen_scope)
                except ValueError:
                    continue
                existing = v.try_get(name, chosen_scope)
                if existing is not None:
                    action = {"skip": "skip", "keep": "skip", "rotate": "rotate"}[on_conflict]
                else:
                    action = "add"

            decisions.append(
                ImportDecision(name=name, scope=chosen_scope, action=action, source_file=str(path))
            )
            value_lookup[(str(path), name)] = value

    summary = projectops.apply_import(v, decisions, value_lookup)
    audit_mod.log(
        "import",
        project=str(project),
        project_name=pname,
        added=[f"{s}/{n}" for n, s in summary["added"]],
        rotated=[f"{s}/{n}" for n, s in summary["rotated"]],
        skipped=[f"{s}/{n}:{reason}" for n, s, reason in summary["skipped"]],
    )

    t = Table(title="Import result")
    t.add_column("Action")
    t.add_column("Name")
    t.add_column("Scope")
    t.add_column("Reason")
    for n, s in summary["added"]:
        t.add_row("[green]added[/green]", n, s, "")
    for n, s in summary["rotated"]:
        t.add_row("[yellow]rotated[/yellow]", n, s, "")
    for n, s, reason in summary["skipped"]:
        t.add_row("[dim]skipped[/dim]", n, s, reason)
    console.print(t)


@main.command()
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, resolve_path=True))
@click.option("--env", default=None, help="Target env; default from .vault.yaml or 'dev'.")
@click.option("--project-name", default=None)
@click.option("--file", "env_file", default=".env", show_default=True)
@click.option(
    "--no-overwrite", is_flag=True, help="Preserve existing values (default is to overwrite)."
)
def sync(
    project_path: str,
    env: str | None,
    project_name: str | None,
    env_file: str,
    no_overwrite: bool,
) -> None:
    """Scan + resolve + inject; update registry. Default is overwrite mode."""
    project = Path(project_path)
    pname = project_name or _read_project_name(project)
    env_name = env or _read_default_env(project) or "dev"
    v = _open_vault()
    result = projectops.sync_project(
        v,
        project,
        pname,
        env_name,
        env_filename=env_file,
        overwrite=not no_overwrite,
    )
    audit_mod.log(
        "sync",
        project=result["project"],
        project_name=pname,
        env=env_name,
        file=result["path"],
        written=result["written"],
        overwrote=result["overwrote"],
        missing=result["missing"],
        revoked=result["revoked"],
    )
    t = Table(title=f"Synced → {result['path']}")
    t.add_column("Category")
    t.add_column("Names")
    if result["written"]:
        t.add_row("[green]written[/green]", ", ".join(result["written"]))
    if result["overwrote"]:
        t.add_row("[green]overwrote[/green]", ", ".join(result["overwrote"]))
    if result["skipped"]:
        t.add_row("[yellow]skipped[/yellow]", ", ".join(result["skipped"].keys()))
    if result["missing"]:
        t.add_row("[red]missing[/red]", ", ".join(result["missing"]))
    if result["revoked"]:
        t.add_row("[red]revoked[/red]", ", ".join(result["revoked"]))
    console.print(t)


@main.command()
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, resolve_path=True))
@click.option("--env", default=None)
@click.option("--project-name", default=None)
@click.option("--file", "env_file", default=".env", show_default=True)
def diff(
    project_path: str,
    env: str | None,
    project_name: str | None,
    env_file: str,
) -> None:
    """Compare the project's .env with what the vault would inject. Never prints values."""
    project = Path(project_path)
    pname = project_name or _read_project_name(project)
    env_name = env or _read_default_env(project) or "dev"
    v = _open_vault()
    report = projectops.diff_project(v, project, pname, env_name, env_filename=env_file)
    pub = report.to_public()
    audit_mod.log(
        "diff",
        project=str(project),
        project_name=pname,
        env=env_name,
        **{k: v for k, v in pub.items() if v},
    )
    t = Table(title=f"diff {project}/{env_file} vs vault ({pname}:{env_name})")
    t.add_column("Category")
    t.add_column("Names")
    for category, items in pub.items():
        if not items:
            continue
        colors = {
            "match": "green",
            "differ": "yellow",
            "only_in_env": "cyan",
            "only_in_vault": "cyan",
            "missing_in_vault": "red",
            "revoked_in_vault": "red",
        }
        c = colors.get(category, "white")
        t.add_row(f"[{c}]{category}[/{c}]", ", ".join(items))
    if t.row_count == 0:
        console.print("[green]In sync.[/green]")
    else:
        console.print(t)


@main.command()
@click.argument("name")
@click.option("--file", "env_file", default=".env", show_default=True)
@click.option("--no-overwrite", is_flag=True, help="Preserve existing values.")
def fanout(name: str, env_file: str, no_overwrite: bool) -> None:
    """Re-inject NAME into every registered project that uses it."""
    validate_name(name)
    v = _open_vault()
    results = projectops.fanout_key(v, name, env_filename=env_file, overwrite=not no_overwrite)
    audit_mod.log(
        "fanout",
        name=name,
        targets=[
            {
                "path": r["path"],
                "project": r["project_name"],
                "env": r["env"],
                "status": r["status"],
            }
            for r in results
        ],
    )
    if not results:
        console.print(f"[dim]No registered projects use {name}.[/dim]")
        return
    t = Table(title=f"Fanout of {name}")
    t.add_column("Project")
    t.add_column("Env")
    t.add_column("Path")
    t.add_column("Status")
    for r in results:
        status_color = {
            "ok": "green",
            "noop": "dim",
            "unavailable": "red",
        }.get(r["status"], "white")
        t.add_row(
            r["project_name"],
            r["env"],
            r["path"],
            f"[{status_color}]{r['status']}[/{status_color}]",
        )
    console.print(t)


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def projects(as_json: bool) -> None:
    """List projects registered with the vault."""
    items = registry_mod.list_all()
    if as_json:
        click.echo(json.dumps(items, ensure_ascii=False, indent=2))
        return
    if not items:
        console.print(
            "[dim]No projects registered. Run `vibe-secrets setup <project>` first.[/dim]"
        )
        return
    t = Table(show_header=True)
    t.add_column("Name")
    t.add_column("Path")
    t.add_column("Default env")
    t.add_column("Last sync")
    t.add_column("Envs")
    for p in items:
        envs = ", ".join(sorted((p.get("keys") or {}).keys())) or "-"
        t.add_row(
            p.get("name", "-"),
            p["path"],
            p.get("default_env", "-"),
            p.get("last_sync", "-"),
            envs,
        )
    console.print(t)


def _read_default_env(project: Path) -> str | None:
    p = project / ".vault.yaml"
    if not p.exists():
        return None
    try:
        import yaml

        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("default_env"), str):
            return data["default_env"]
    except Exception:
        pass
    return None


# ---------- TUI ----------


@main.command()
def tui() -> None:
    """Launch the interactive vault manager (TUI)."""
    from .tui import run_tui

    run_tui()


# ---------- agent sub-group ----------


@main.group()
def agent() -> None:
    """Agent-safe commands. JSON output; raw values never returned."""


@agent.command("list-names")
@click.option("--scope", default=None)
def agent_list_names(scope: str | None) -> None:
    """List available secret names (no values)."""
    v = _open_vault()
    recs = v.list(scope)
    out = [
        {
            "name": r.name,
            "scope": r.scope,
            "status": r.status,
            "last_used_at": r.last_used_at,
        }
        for r in recs
    ]
    audit_mod.log("agent.list-names", scope=scope, count=len(out))
    click.echo(json.dumps(out, ensure_ascii=False))


@agent.command("scan")
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, resolve_path=True))
def agent_scan(project_path: str) -> None:
    """Emit the set of env-var names found in a project, as a JSON array."""
    names = sorted(scanner.scan(Path(project_path)))
    audit_mod.log("agent.scan", project=project_path, count=len(names))
    click.echo(json.dumps(names, ensure_ascii=False))


@agent.command("inject")
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, resolve_path=True))
@click.option("--env", default="dev", show_default=True)
@click.option("--project-name", default=None)
@click.option("--file", "env_file", default=".env", show_default=True)
@click.option("--names", default=None, help="Comma-separated names. Omit to use the scanner.")
@click.option("--overwrite", is_flag=True)
def agent_inject(
    project_path: str,
    env: str,
    project_name: str | None,
    env_file: str,
    names: str | None,
    overwrite: bool,
) -> None:
    """Inject secrets into <project>/<.env>. Returns JSON; never emits values."""
    project = Path(project_path)
    pname = project_name or _read_project_name(project)
    if names:
        name_list = [n.strip() for n in names.split(",") if n.strip()]
    else:
        name_list = sorted(scanner.scan(project, exclude=[project / env_file]))
    v = _open_vault()
    resolutions = resolver_mod.resolve(v, name_list, pname, env)
    result = envwriter.write_env(project, env_file, resolutions, overwrite=overwrite)
    for n, scope in result["written"].items():
        v.touch_used(n, scope, pname)
    if result["written"]:
        registry_mod.record_inject(project, pname, env, list(result["written"].keys()))

    public = {
        "project": str(project),
        "project_name": pname,
        "env": env,
        "path": result["path"],
        "written": list(result["written"].keys()),
        "overwrote": list(result["overwrote"].keys()),
        "skipped": result["skipped"],
        "missing": result["missing"],
        "revoked": result["revoked"],
    }
    audit_mod.log(
        "agent.inject", **{k: v for k, v in public.items() if k != "path"}, file=result["path"]
    )
    click.echo(json.dumps(public, ensure_ascii=False))


@agent.command("status")
def agent_status() -> None:
    """Return vault status as JSON."""
    v = Vault()
    info = v.stats()
    try:
        info["has_master"] = has_master()
    except KeystoreError:
        info["has_master"] = False
    audit_mod.log("agent.status")
    click.echo(json.dumps(info, ensure_ascii=False))


@agent.command("setup")
@click.argument("project_path", type=click.Path(file_okay=False, resolve_path=True))
@click.option("--project-name", default=None)
@click.option("--env", default="dev", show_default=True)
@click.option(
    "--emit", "emit", multiple=True, help="agents, claude, cursor, copilot, windsurf, all"
)
def agent_setup(
    project_path: str,
    project_name: str | None,
    env: str,
    emit: tuple[str, ...],
) -> None:
    """Onboard a project: write .vault.yaml + rules files + .gitignore. JSON output."""
    project = Path(project_path)
    project.mkdir(parents=True, exist_ok=True)
    try:
        result = projectops.setup_project(
            project, project_name, env, emit=list(emit) if emit else None
        )
    except ValueError as e:
        raise click.ClickException(str(e))
    audit_mod.log(
        "agent.setup",
        project=result["project"],
        project_name=result["project_name"],
        env=result["default_env"],
        emits={k: v["status"] for k, v in result["emits"].items()},
    )
    click.echo(json.dumps(result, ensure_ascii=False))


@agent.command("sync")
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, resolve_path=True))
@click.option("--env", default=None)
@click.option("--project-name", default=None)
@click.option("--file", "env_file", default=".env", show_default=True)
@click.option("--no-overwrite", is_flag=True)
def agent_sync(
    project_path: str,
    env: str | None,
    project_name: str | None,
    env_file: str,
    no_overwrite: bool,
) -> None:
    """Scan + resolve + inject for a project. JSON output; no values."""
    project = Path(project_path)
    pname = project_name or _read_project_name(project)
    env_name = env or _read_default_env(project) or "dev"
    v = _open_vault()
    result = projectops.sync_project(
        v,
        project,
        pname,
        env_name,
        env_filename=env_file,
        overwrite=not no_overwrite,
    )
    audit_mod.log(
        "agent.sync",
        project=result["project"],
        project_name=pname,
        env=env_name,
        written=result["written"],
        overwrote=result["overwrote"],
        missing=result["missing"],
        revoked=result["revoked"],
    )
    click.echo(json.dumps(result, ensure_ascii=False))


@agent.command("diff")
@click.argument("project_path", type=click.Path(exists=True, file_okay=False, resolve_path=True))
@click.option("--env", default=None)
@click.option("--project-name", default=None)
@click.option("--file", "env_file", default=".env", show_default=True)
def agent_diff(
    project_path: str,
    env: str | None,
    project_name: str | None,
    env_file: str,
) -> None:
    """Structural diff between the project's .env and the vault. Never returns values."""
    project = Path(project_path)
    pname = project_name or _read_project_name(project)
    env_name = env or _read_default_env(project) or "dev"
    v = _open_vault()
    report = projectops.diff_project(v, project, pname, env_name, env_filename=env_file)
    public = {
        "project": str(project),
        "project_name": pname,
        "env": env_name,
        **report.to_public(),
    }
    audit_mod.log("agent.diff", project=str(project), project_name=pname, env=env_name)
    click.echo(json.dumps(public, ensure_ascii=False))


@agent.command("fanout")
@click.argument("name")
@click.option("--file", "env_file", default=".env", show_default=True)
@click.option("--no-overwrite", is_flag=True)
def agent_fanout(name: str, env_file: str, no_overwrite: bool) -> None:
    """Re-inject NAME into every registered project that uses it. JSON output."""
    validate_name(name)
    v = _open_vault()
    results = projectops.fanout_key(
        v,
        name,
        env_filename=env_file,
        overwrite=not no_overwrite,
    )
    audit_mod.log("agent.fanout", name=name, target_count=len(results))
    click.echo(json.dumps(results, ensure_ascii=False))


@agent.command("projects")
def agent_projects() -> None:
    """List registered projects. JSON output."""
    items = registry_mod.list_all()
    audit_mod.log("agent.projects", count=len(items))
    click.echo(json.dumps(items, ensure_ascii=False))


# ---------- skill install (user-level) ----------


@main.group()
def skill() -> None:
    """Install or remove user-level agent-assistant integrations (Claude Code skill)."""


@skill.command("install")
@click.option("--force", is_flag=True, help="Overwrite if the file exists with different content.")
def skill_install(force: bool) -> None:
    """Install the Claude Code skill into ~/.claude/skills/vibe-secrets/SKILL.md."""
    result = installer.install_claude_skill(force=force)
    audit_mod.log("skill.install", target=result.target, status=result.status, path=result.path)
    color = {
        "installed": "green",
        "unchanged": "dim",
        "skipped-exists": "yellow",
        "error": "red",
    }.get(result.status, "white")
    console.print(f"[{color}]{result.status}[/{color}] → {result.path}")
    if result.detail:
        console.print(f"  {result.detail}")
    if result.status == "skipped-exists":
        raise click.exceptions.Exit(code=2)


@skill.command("uninstall")
def skill_uninstall() -> None:
    """Remove the Claude Code skill from ~/.claude/skills/vibe-secrets/."""
    result = installer.uninstall_claude_skill()
    audit_mod.log("skill.uninstall", target=result.target, status=result.status)
    console.print(f"{result.status} → {result.path}")


@skill.command("status")
def skill_status() -> None:
    """Show installation status of user-level integrations."""
    results = installer.skill_status()
    t = Table(show_header=True)
    t.add_column("Target")
    t.add_column("Path")
    t.add_column("Status")
    t.add_column("Note")
    for r in results:
        t.add_row(r.target, r.path, r.status, r.detail or "")
    console.print(t)


# ---------- bootstrap (new-machine one-shot) ----------


@main.command()
@click.argument(
    "project_path",
    type=click.Path(file_okay=False, resolve_path=True),
    required=False,
)
@click.option("--project-name", default=None, help="Override project name for optional setup.")
@click.option("--env", default="dev", show_default=True)
@click.option("--no-skill", is_flag=True, help="Skip installing the Claude Code skill.")
@click.option("--force-skill", is_flag=True, help="Overwrite an existing Claude Code skill.")
@click.option(
    "--emit", "emit", multiple=True, help="Rules files to emit for PROJECT_PATH (if given)."
)
def bootstrap(
    project_path: str | None,
    project_name: str | None,
    env: str,
    no_skill: bool,
    force_skill: bool,
    emit: tuple[str, ...],
) -> None:
    """New-machine one-shot: create the vault, install the Claude skill, optionally set up a project."""
    summary: dict[str, object] = {}

    # 1. Master key in keychain.
    try:
        if not has_master():
            create_master()
            summary["master"] = "created"
        else:
            summary["master"] = "existing"
    except KeystoreError as e:
        raise click.ClickException(str(e))

    # 2. Vault file.
    v = Vault()
    if v.exists():
        summary["vault"] = "existing"
    else:
        v.init_empty()
        audit_mod.log("init", path=str(v.path))
        summary["vault"] = "created"

    # 3. Claude Code skill.
    if no_skill:
        summary["skill"] = "skipped"
    else:
        sk = installer.install_claude_skill(force=force_skill)
        summary["skill"] = sk.status
        summary["skill_path"] = sk.path
        audit_mod.log("skill.install", target=sk.target, status=sk.status, path=sk.path)

    # 4. Optional project setup.
    if project_path:
        project = Path(project_path)
        project.mkdir(parents=True, exist_ok=True)
        try:
            setup_result = projectops.setup_project(
                project, project_name, env, emit=list(emit) if emit else None
            )
        except ValueError as e:
            raise click.ClickException(str(e))
        audit_mod.log(
            "setup",
            project=setup_result["project"],
            project_name=setup_result["project_name"],
            env=setup_result["default_env"],
            emits={k: s["status"] for k, s in setup_result["emits"].items()},
        )
        summary["project"] = setup_result["project_name"]
        summary["project_path"] = setup_result["project"]
        summary["project_emits"] = {k: s["status"] for k, s in setup_result["emits"].items()}

    audit_mod.log("bootstrap", **{k: str(v) for k, v in summary.items()})

    t = Table(title="vibe-secrets bootstrap", show_header=False, box=None)
    for k, v in summary.items():
        t.add_row(str(k), str(v))
    console.print(t)
    console.print()
    console.print("[bold]Next steps[/bold]")
    console.print("  1. Add a key:  [cyan]vibe-secrets add ANTHROPIC_API_KEY --scope global[/cyan]")
    if not project_path:
        console.print("  2. In a project folder: [cyan]vibe-secrets setup .[/cyan]")
        console.print("  3. Then: [cyan]vibe-secrets sync .[/cyan]")
    else:
        console.print(
            "  2. From that project:  [cyan]vibe-secrets sync " + project_path + "[/cyan]"
        )


# ---------- backup / restore / reset-master ----------


def _prompt_passphrase(confirm: bool) -> str:
    if not sys.stdin.isatty():
        value = sys.stdin.read()
        if value.endswith("\n"):
            value = value[:-1]
        return value
    return click.prompt(
        "Passphrase",
        hide_input=True,
        confirmation_prompt=confirm,
    )


@main.command()
@click.argument("path", type=click.Path(dir_okay=False, writable=True))
def backup(path: str) -> None:
    """Write an encrypted, portable backup of the vault + registry.

    Protected by a passphrase you choose. The backup file is safe to move
    between machines — it is not tied to the local OS keychain.
    """
    from . import backup as backup_mod  # avoid loading crypto at import time

    _open_vault()  # raises with a friendly message if no vault
    passphrase = _prompt_passphrase(confirm=True)
    if not passphrase:
        raise click.ClickException("Passphrase must not be empty.")
    summary = backup_mod.write_backup(path, passphrase)
    audit_mod.log(
        "backup",
        path=summary["path"],
        records=summary["records"],
        projects=summary["projects"],
    )
    t = Table(show_header=False, box=None)
    for k, v in summary.items():
        t.add_row(str(k), str(v))
    console.print(t)
    console.print(
        "[green]Backup written.[/green] Store the passphrase somewhere safe — "
        "without it, the backup cannot be restored."
    )


@main.command()
@click.argument("path", type=click.Path(exists=True, dir_okay=False, readable=True))
@click.option(
    "--mode",
    type=click.Choice(["replace", "merge"]),
    default="replace",
    show_default=True,
    help="replace = overwrite local state; merge = add entries missing locally.",
)
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def restore(path: str, mode: str, yes: bool) -> None:
    """Restore from a vibe-secrets backup file."""
    from . import backup as backup_mod

    if not _confirm(
        f"Restore {path} with mode={mode}? This will modify the local vault.",
        yes,
    ):
        raise click.Abort()
    passphrase = _prompt_passphrase(confirm=False)
    try:
        summary = backup_mod.restore_from_backup(path, passphrase, mode=mode)
    except backup_mod.BackupError as e:
        raise click.ClickException(str(e))
    audit_mod.log("restore", path=str(path), mode=mode, **summary)
    t = Table(show_header=False, box=None)
    for k, v in summary.items():
        t.add_row(str(k), str(v))
    console.print(t)
    console.print("[green]Restore complete.[/green]")


@main.command("reset-master")
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def reset_master(yes: bool) -> None:
    """Re-encrypt the vault with a fresh master key (rotates the keychain entry).

    Creates a pre-reset backup of the old ciphertext on disk as a safety net.
    """
    v = _open_vault()
    if not _confirm(
        "Generate a NEW master key and re-encrypt the vault? "
        "The old key in the keychain will be replaced.",
        yes,
    ):
        raise click.Abort()
    try:
        result = v.reset_master()
    except VaultError as e:
        raise click.ClickException(str(e))
    audit_mod.log(
        "reset-master",
        path=result["path"],
        backup=result["backup"],
        records=result["records"],
    )
    t = Table(show_header=False, box=None)
    t.add_row("Vault", result["path"])
    t.add_row("Records re-encrypted", str(result["records"]))
    t.add_row("Pre-reset backup", result["backup"] or "(no prior vault)")
    console.print(t)
    console.print("[green]Master key rotated.[/green]")


# ---------- shell completion ----------

_COMPLETION_LINES = {
    "bash": 'eval "$(_VIBE_SECRETS_COMPLETE=bash_source vibe-secrets)"',
    "zsh": 'eval "$(_VIBE_SECRETS_COMPLETE=zsh_source vibe-secrets)"',
    "fish": "eval (env _VIBE_SECRETS_COMPLETE=fish_source vibe-secrets)",
}


@main.group()
def completion() -> None:
    """Shell completion setup for bash / zsh / fish."""


@completion.command("show")
@click.argument("shell", type=click.Choice(sorted(_COMPLETION_LINES.keys())))
def completion_show(shell: str) -> None:
    """Print the completion line for SHELL. Append its output to your shell rc:

    \b
        vibe-secrets completion show zsh  >> ~/.zshrc
        source ~/.zshrc
    """
    click.echo(_COMPLETION_LINES[shell])


@completion.command("install")
@click.argument("shell", type=click.Choice(sorted(_COMPLETION_LINES.keys())))
@click.option(
    "--rc",
    "rc_path",
    default=None,
    help="Override the shell rc file path. Default: ~/.bashrc / ~/.zshrc / "
    "~/.config/fish/config.fish.",
)
def completion_install(shell: str, rc_path: str | None) -> None:
    """Append the completion line to your shell rc (idempotent)."""
    defaults = {
        "bash": Path.home() / ".bashrc",
        "zsh": Path.home() / ".zshrc",
        "fish": Path.home() / ".config" / "fish" / "config.fish",
    }
    target = Path(rc_path) if rc_path else defaults[shell]
    line = _COMPLETION_LINES[shell]
    marker = "# vibe-secrets completion"
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    if marker in existing and line in existing:
        console.print(f"[dim]Already installed in {target}[/dim]")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(f"\n{marker}\n{line}\n")
    audit_mod.log("completion.install", shell=shell, path=str(target))
    console.print(
        f"[green]Installed[/green] completion for {shell} → {target}\n"
        f"Reload your shell, or `source {target}`."
    )


if __name__ == "__main__":
    main()
