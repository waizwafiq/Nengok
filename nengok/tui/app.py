"""
Textual `App` subclass for `nengok review`.

The app boots a placeholder welcome screen and exits cleanly on Ctrl-C
or `q`. The cluster-list, detail, and approval screens land in the
follow-up subphase; this scaffold only owns the lifecycle, the app
title, and the shared `TuiApiClient` reference every screen reads.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.containers import Center, Middle
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from nengok.tui.api_client import TuiApiClient


class PlaceholderScreen(Screen):
    """One-line welcome screen used until the real cluster list lands."""

    def compose(self) -> ComposeResult:
        yield Header()
        with Middle(), Center():
            yield Static(
                "Nengok review TUI. Press q to quit.",
                id="nengok-tui-placeholder",
            )
        yield Footer()


class NengokReviewApp(App[None]):
    """Root Textual app that hosts the cluster list and detail screens."""

    TITLE = "Nengok review"
    SUB_TITLE = "Approve fixes without leaving the terminal"
    BINDINGS: ClassVar[list[BindingType]] = [("q", "quit", "Quit")]

    def __init__(self, api_client: TuiApiClient) -> None:
        super().__init__()
        self.api_client = api_client

    def on_mount(self) -> None:
        self.push_screen(PlaceholderScreen())

    def action_quit(self) -> None:
        self.exit()
