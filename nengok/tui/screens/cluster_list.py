"""
Cluster list screen: one row per open cluster, keyboard-driven navigation.

Mirrors the columns the dashboard's `ClusterCard` renders, so the two
operator surfaces stay aligned on what information is surfaced first.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

if TYPE_CHECKING:
    from nengok.tui.app import NengokReviewApp


class ClusterListScreen(Screen):
    """Top-level cluster table. Enter drills into a cluster."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("r", "refresh", "Refresh"),
        ("j", "cursor_down", "Down"),
        ("k", "cursor_up", "Up"),
        ("o", "open_cluster", "Open"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._cluster_ids: list[str] = []
        self._status: Static | None = None
        self._table: DataTable | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            self._status = Static("Loading clusters...", id="cluster-list-status")
            yield self._status
            self._table = DataTable(zebra_stripes=True, cursor_type="row")
            self._table.add_columns("ID", "Name", "Project", "Status", "Members", "Updated")
            yield self._table
        yield Footer()

    async def on_mount(self) -> None:
        await self._load_rows()

    async def action_refresh(self) -> None:
        await self._load_rows()

    def action_cursor_down(self) -> None:
        if self._table is not None:
            self._table.action_cursor_down()

    def action_cursor_up(self) -> None:
        if self._table is not None:
            self._table.action_cursor_up()

    async def action_open_cluster(self) -> None:
        await self._open_cursor_row()

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        del event
        await self._open_cursor_row()

    async def _open_cursor_row(self) -> None:
        from nengok.tui.screens.cluster_detail import ClusterDetailScreen

        if self._table is None:
            return
        cursor_row = self._table.cursor_row
        if cursor_row < 0 or cursor_row >= len(self._cluster_ids):
            return
        cluster_id = self._cluster_ids[cursor_row]
        await self.app.push_screen(ClusterDetailScreen(cluster_id=cluster_id))

    def action_quit(self) -> None:
        self.app.exit()

    async def _load_rows(self) -> None:
        app = _app(self)
        assert self._table is not None
        assert self._status is not None
        try:
            clusters = await app.api_client.list_clusters()
        except Exception as exc:
            self._status.update(f"Failed to load clusters: {exc}")
            return

        self._table.clear()
        self._cluster_ids = []
        for row in clusters:
            cluster_id = str(row.get("cluster_id", ""))
            name = str(row.get("name", "<unnamed>"))
            project = str(row.get("project") or "-")
            status = str(row.get("status", "open"))
            members = _member_count(row.get("member_spans_json"))
            updated = str(row.get("updated_at", ""))
            self._table.add_row(cluster_id, name, project, status, str(members), updated)
            self._cluster_ids.append(cluster_id)

        if not clusters:
            self._status.update("No clusters found. Seed traces and run `nengok run` to populate the list.")
        else:
            self._status.update(
                f"{len(clusters)} cluster(s). j/k to move, Enter or o to open, r to refresh, q to quit."
            )


def _member_count(value: Any) -> int:
    if not isinstance(value, str):
        return 0
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return 0
    return len(parsed) if isinstance(parsed, list) else 0


def _app(screen: Screen) -> NengokReviewApp:
    from nengok.tui.app import NengokReviewApp

    app = screen.app
    assert isinstance(app, NengokReviewApp)
    return app
