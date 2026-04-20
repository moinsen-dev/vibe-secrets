"""Minimal TUI matching the wireframe in concept/wireframe.md.

Three panels: scope tree (left), key details (right), audit tail (bottom).
Actions: reveal (confirm), copy, rotate (prompts for value), revoke.

Raw values are masked by default and never appear in the scope tree.
"""

from __future__ import annotations

from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Static,
    Tree,
)

from . import audit as audit_mod
from . import clipboard as clip
from .models import KeyRecord
from .vault import NotFound, Vault


class _ConfirmReveal(ModalScreen[bool]):
    """Modal: confirm revealing a raw secret value."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, scope: str, name: str) -> None:
        super().__init__()
        self._scope = scope
        self._name = name

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Label(f"Reveal raw value for {self._scope}/{self._name}?")
            with Horizontal(classes="modal-actions"):
                yield Button("Reveal", id="ok", variant="warning")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "ok")

    def action_cancel(self) -> None:
        self.dismiss(False)


class _RotatePrompt(ModalScreen[Optional[str]]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, scope: str, name: str) -> None:
        super().__init__()
        self._scope = scope
        self._name = name

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal"):
            yield Label(f"New value for {self._scope}/{self._name}")
            yield Input(password=True, id="value")
            with Horizontal(classes="modal-actions"):
                yield Button("Rotate", id="ok", variant="warning")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok":
            self.dismiss(self.query_one("#value", Input).value)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class VaultApp(App):
    CSS = """
    Screen { background: $surface; }
    #wrap { height: 1fr; }
    #tree { width: 36; border-right: solid $primary; }
    #detail { padding: 1 2; }
    #audit { height: 6; border-top: solid $primary; padding: 0 1; }
    .modal {
        align: center middle;
        border: thick $primary;
        padding: 1 2;
        background: $panel;
        width: 60;
    }
    .modal-actions { align: right middle; margin-top: 1; }
    #value-label { color: $text-muted; }
    #value-field { color: $text; }
    #status-active { color: $success; }
    #status-revoked { color: $error; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._vault = Vault()
        self._selected: KeyRecord | None = None
        self._revealed = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False, name="vibe-secrets")
        with Horizontal(id="wrap"):
            yield Tree("Scopes", id="tree")
            with Vertical(id="detail"):
                yield Static("Select a secret on the left.", id="detail-body")
                with Horizontal(id="actions"):
                    yield Button("Reveal", id="btn-reveal", disabled=True)
                    yield Button("Copy", id="btn-copy", disabled=True)
                    yield Button("Rotate", id="btn-rotate", disabled=True)
                    yield Button("Revoke", id="btn-revoke", disabled=True)
        yield DataTable(id="audit", zebra_stripes=False, cursor_type="none")
        yield Footer()

    def on_mount(self) -> None:
        if not self._vault.exists():
            body = self.query_one("#detail-body", Static)
            body.update(
                "[bold red]No vault found.[/bold red]\n\n"
                "Run `vibe-secrets init` in a terminal first."
            )
            return
        self._refresh_tree()
        self._refresh_audit()

    def _refresh_tree(self) -> None:
        tree: Tree = self.query_one("#tree", Tree)
        tree.clear()
        tree.root.label = "Scopes"
        tree.root.expand()
        by_scope: dict[str, list[KeyRecord]] = {}
        for r in self._vault.list():
            by_scope.setdefault(r.scope, []).append(r)
        for scope in sorted(by_scope.keys()):
            node = tree.root.add(scope, expand=True)
            for rec in sorted(by_scope[scope], key=lambda x: x.name):
                label = rec.name if rec.status == "active" else f"{rec.name} (revoked)"
                node.add_leaf(label, data=rec)

    def _refresh_audit(self) -> None:
        tbl: DataTable = self.query_one("#audit", DataTable)
        tbl.clear(columns=True)
        tbl.add_columns("Time", "Actor", "Op", "Details")
        for e in audit_mod.tail(50):
            details = ", ".join(f"{k}={v}" for k, v in e.items() if k not in ("ts", "op", "actor"))
            tbl.add_row(
                e.get("ts", "-"),
                e.get("actor", "-"),
                e.get("op", "-"),
                details,
            )

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        node = event.node
        if node.data is None:
            self._set_selected(None)
            return
        self._set_selected(node.data)

    def _set_selected(self, rec: KeyRecord | None) -> None:
        self._selected = rec
        self._revealed = False
        body = self.query_one("#detail-body", Static)
        if rec is None:
            body.update("Select a secret on the left.")
            self._toggle_actions(enabled=False)
            return
        self._render_detail()
        # Disable actions for revoked records except 'Rotate' (to replace).
        active = rec.status == "active"
        self._set_action("btn-reveal", active)
        self._set_action("btn-copy", active)
        self._set_action("btn-rotate", True)
        self._set_action("btn-revoke", active)

    def _render_detail(self) -> None:
        rec = self._selected
        if rec is None:
            return
        status_color = "green" if rec.status == "active" else "red"
        masked = "*" * 12
        value_line = rec.value if self._revealed else masked
        body = self.query_one("#detail-body", Static)
        body.update(
            f"[bold]{rec.scope}/{rec.name}[/bold]\n"
            f"Status : [{status_color}]{rec.status}[/{status_color}]\n"
            f"Created: {rec.created_at}\n"
            f"Last   : {rec.last_used_at or '-'}\n"
            f"Project: {rec.last_injected_project or '-'}\n"
            f"\n"
            f"Value  : {value_line}\n"
        )

    def _toggle_actions(self, enabled: bool) -> None:
        for bid in ("btn-reveal", "btn-copy", "btn-rotate", "btn-revoke"):
            self._set_action(bid, enabled)

    def _set_action(self, bid: str, enabled: bool) -> None:
        try:
            self.query_one(f"#{bid}", Button).disabled = not enabled
        except Exception:
            pass

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        rec = self._selected
        if rec is None:
            return
        bid = event.button.id
        if bid == "btn-reveal":
            confirmed = await self.push_screen_wait(_ConfirmReveal(rec.scope, rec.name))
            if confirmed:
                self._revealed = True
                audit_mod.log("tui.reveal", name=rec.name, scope=rec.scope)
                self._render_detail()
        elif bid == "btn-copy":
            ok = clip.copy_to_clipboard(rec.value)
            audit_mod.log("tui.copy", name=rec.name, scope=rec.scope, ok=ok)
            self.notify(
                "Copied to clipboard" if ok else "Clipboard tool not found",
                severity=("information" if ok else "error"),
            )
        elif bid == "btn-rotate":
            new_val = await self.push_screen_wait(_RotatePrompt(rec.scope, rec.name))
            if new_val:
                try:
                    self._vault.rotate(rec.name, rec.scope, new_val)
                    audit_mod.log("tui.rotate", name=rec.name, scope=rec.scope)
                    self.notify("Rotated")
                    self._refresh_tree()
                    self._refresh_audit()
                    try:
                        self._selected = self._vault.get(rec.name, rec.scope)
                        self._render_detail()
                    except NotFound:
                        pass
                except Exception as e:
                    self.notify(f"Rotate failed: {e}", severity="error")
        elif bid == "btn-revoke":
            try:
                self._vault.revoke(rec.name, rec.scope)
                audit_mod.log("tui.revoke", name=rec.name, scope=rec.scope)
                self.notify("Revoked", severity="warning")
                self._refresh_tree()
                self._refresh_audit()
                self._selected = self._vault.get(rec.name, rec.scope)
                self._render_detail()
                self._toggle_actions(enabled=False)
                self._set_action("btn-rotate", True)
            except Exception as e:
                self.notify(f"Revoke failed: {e}", severity="error")

    def action_refresh(self) -> None:
        self._refresh_tree()
        self._refresh_audit()


def run_tui() -> None:
    VaultApp().run()


if __name__ == "__main__":
    run_tui()
