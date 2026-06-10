"""
Cluster detail screen: one tab per artifact (hypothesis, experiment, prompt, RCA).

The experiment tab mirrors the dashboard's `ExperimentTable`, and the
prompt tab renders mustache placeholders in distinct colors so the same
visual contract holds between the browser and the terminal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from rich.json import JSON
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static, TabbedContent, TabPane

if TYPE_CHECKING:
    from nengok.tui.app import NengokReviewApp


class ClusterDetailScreen(Screen):
    """Tabbed detail view. `a` approves, `x` rejects, `Esc` returns to the list."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("a", "approve", "Approve"),
        ("x", "reject", "Reject"),
        ("escape", "back", "Back"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, cluster_id: str) -> None:
        super().__init__()
        self.cluster_id = cluster_id
        self._cluster: dict[str, Any] | None = None
        self._experiment: dict[str, Any] | None = None
        self._artifacts: dict[str, Any] | None = None
        self._links: list[dict[str, Any]] = []
        self._toast: Static | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            self._toast = Static("Loading cluster...", id="cluster-detail-toast")
            yield self._toast
            with TabbedContent(initial="tab-hypothesis"):
                with TabPane("Hypothesis", id="tab-hypothesis"):
                    yield Static("(loading)", id="hypothesis-body")
                with TabPane("Experiment", id="tab-experiment"):
                    table = DataTable(zebra_stripes=True, id="experiment-table")
                    table.add_columns("Case", "Baseline", "Fix")
                    yield table
                with TabPane("Prompt", id="tab-prompt"):
                    yield Static("(loading)", id="prompt-body")
                with TabPane("RCA", id="tab-rca"):
                    yield Static("(loading)", id="rca-body")
                with TabPane("Links", id="tab-links"):
                    links_table = DataTable(zebra_stripes=True, id="links-table")
                    links_table.add_columns("Project", "Cluster", "Status", "Confidence", "Rationale")
                    yield links_table
        yield Footer()

    async def on_mount(self) -> None:
        await self._load()

    async def _load(self) -> None:
        app = _app(self)
        try:
            self._cluster = await app.api_client.get_cluster(self.cluster_id)
        except Exception as exc:
            self._update_toast(f"Failed to load cluster {self.cluster_id}: {exc}")
            return

        self._experiment = await app.api_client.latest_experiment(self.cluster_id)
        self._artifacts = await app.api_client.get_artifacts(self.cluster_id)
        self._links = await app.api_client.list_cluster_links(self.cluster_id)

        self._render_hypothesis()
        self._render_experiment()
        self._render_prompt()
        self._render_rca()
        self._render_links()
        name = self._cluster.get("name", self.cluster_id)
        self._update_toast(f"{name} ({self.cluster_id}). a=approve, x=reject, Esc=back.")

    def _render_hypothesis(self) -> None:
        assert self._cluster is not None
        body = self.query_one("#hypothesis-body", Static)
        raw = self._cluster.get("hypothesis_json")
        if not raw:
            body.update("No hypothesis recorded for this cluster yet.")
            return
        try:
            body.update(JSON(raw))
        except ValueError:
            body.update(str(raw))

    def _render_experiment(self) -> None:
        table = self.query_one("#experiment-table", DataTable)
        table.clear()
        if self._experiment is None:
            return
        per_case = self._experiment.get("per_case") or []
        for case in per_case:
            if not isinstance(case, dict):
                continue
            table.add_row(
                str(case.get("case_id") or case.get("name") or "<case>"),
                _format_pass_value(case.get("baseline")),
                _format_pass_value(case.get("fix")),
            )

    def _render_prompt(self) -> None:
        body = self.query_one("#prompt-body", Static)
        text = (self._artifacts or {}).get("prompt") if self._artifacts else None
        if not text:
            body.update("No prompt artifact recorded for this cluster yet.")
            return
        body.update(_highlight_prompt_diff(str(text)))

    def _render_rca(self) -> None:
        body = self.query_one("#rca-body", Static)
        text = (self._artifacts or {}).get("rca") if self._artifacts else None
        body.update(str(text) if text else "No RCA recorded for this cluster yet.")

    def _render_links(self) -> None:
        table = self.query_one("#links-table", DataTable)
        table.clear()
        for link in self._links:
            if not isinstance(link, dict):
                continue
            confidence = link.get("confidence")
            table.add_row(
                str(link.get("linked_project") or "-"),
                str(link.get("linked_name") or link.get("linked_cluster_id") or "<cluster>"),
                str(link.get("linked_status") or "-"),
                f"{confidence:.2f}" if isinstance(confidence, int | float) else "-",
                str(link.get("rationale") or ""),
            )

    def action_approve(self) -> None:
        self._open_modal("approved")

    def action_reject(self) -> None:
        self._open_modal("rejected")

    def _open_modal(self, decision: str) -> None:
        from nengok.tui.screens.approval_modal import ApprovalModalScreen

        def _after(result: bool | None) -> None:
            if result is True:
                self._update_toast(f"{decision.capitalize()} recorded for {self.cluster_id}.")
                self.run_worker(self._load(), exclusive=True)

        self.app.push_screen(
            ApprovalModalScreen(cluster_id=self.cluster_id, decision=decision),
            _after,
        )

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_quit(self) -> None:
        self.app.exit()

    def _update_toast(self, message: str) -> None:
        if self._toast is not None:
            self._toast.update(message)


def _format_pass_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "pass" if value else "fail"
    if isinstance(value, int | float):
        return f"{value:.2f}"
    return str(value)


def _highlight_prompt_diff(prompt: str) -> Text:
    """
    Color added/removed lines and mustache placeholders for the prompt diff tab.

    Lines starting with `+` are added, `-` are removed, every other line
    is context. Mustache `{{...}}` ranges get the same yellow accent the
    React diff applies so reviewers can tell variables from prose.
    """
    text = Text()
    for raw_line in prompt.splitlines(keepends=True):
        if raw_line.startswith("+"):
            text.append(raw_line, style="green")
        elif raw_line.startswith("-"):
            text.append(raw_line, style="red")
        else:
            text.append(raw_line)
    text.highlight_regex(r"\{\{[^}]+\}\}", "bold yellow")
    return text


def _app(screen: Screen) -> NengokReviewApp:
    from nengok.tui.app import NengokReviewApp

    app = screen.app
    assert isinstance(app, NengokReviewApp)
    return app
