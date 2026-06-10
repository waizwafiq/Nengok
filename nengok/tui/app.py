"""
Textual `App` subclass for `nengok review`.

The app boots the cluster list as its root screen, exits cleanly on
Ctrl-C or `q`, and shares a single `TuiApiClient` with every child
screen so navigation never reopens an HTTP session.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import App
from textual.binding import BindingType

from nengok.tui.api_client import TuiApiClient


class NengokReviewApp(App[None]):
    """Root Textual app that hosts the cluster list and detail screens."""

    TITLE = "Nengok review"
    SUB_TITLE = "Approve fixes without leaving the terminal"
    BINDINGS: ClassVar[list[BindingType]] = [("q", "quit", "Quit")]

    def __init__(self, api_client: TuiApiClient) -> None:
        super().__init__()
        self.api_client = api_client

    def on_mount(self) -> None:
        from nengok.tui.screens.cluster_list import ClusterListScreen

        self.push_screen(ClusterListScreen())

    async def action_quit(self) -> None:
        self.exit()
