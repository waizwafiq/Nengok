"""
Approval modal: asks for a one-line reason, posts to the FastAPI server.

Triggered from the cluster detail screen by `a` (approve) or `x`
(reject). Surfaces success as a toast and reports API errors verbatim
so the operator can decide whether to retry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Select, Static

from nengok.tui.api_client import APPROVAL_SOURCE_TUI, TuiApiError

if TYPE_CHECKING:
    from nengok.tui.app import NengokReviewApp

FEEDBACK_TAG_OPTIONS: tuple[tuple[str, str], ...] = (
    ("Duplicate cluster", "duplicate_cluster"),
    ("Mixed root causes", "mixed_root_causes"),
    ("Not a failure", "not_a_failure"),
)


class ApprovalModalScreen(ModalScreen[bool]):
    """Single-line prompt for an approval reason; returns True on a recorded decision."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, *, cluster_id: str, decision: str) -> None:
        super().__init__()
        self.cluster_id = cluster_id
        self.decision = decision
        self._status: Static | None = None
        self._reason_input: Input | None = None
        self._tag_select: Select[str] | None = None

    def compose(self) -> ComposeResult:
        verb = "Approve" if self.decision == "approved" else "Reject"
        with Vertical(id="approval-modal"):
            yield Static(f"{verb} cluster {self.cluster_id}", id="approval-title")
            yield Static("Reason (optional, one line):")
            self._reason_input = Input(placeholder="why this decision", id="approval-reason")
            yield self._reason_input
            yield Static("Clustering feedback (optional):")
            self._tag_select = Select(
                FEEDBACK_TAG_OPTIONS,
                prompt="No clustering feedback",
                id="approval-feedback-tag",
            )
            yield self._tag_select
            yield Button("Submit", id="approval-submit", variant="primary")
            yield Button("Cancel", id="approval-cancel")
            self._status = Static("", id="approval-status")
            yield self._status

    def on_mount(self) -> None:
        if self._reason_input is not None:
            self._reason_input.focus()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "approval-cancel":
            self.dismiss(False)
            return
        if event.button.id == "approval-submit":
            await self._submit()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        del event
        await self._submit()

    async def _submit(self) -> None:
        app = _app(self)
        reason = (self._reason_input.value if self._reason_input else "").strip() or None
        feedback_tag: str | None = None
        if self._tag_select is not None and self._tag_select.value is not Select.BLANK:
            feedback_tag = str(self._tag_select.value)
        if self._status is not None:
            self._status.update("Submitting...")
        try:
            await app.api_client.submit_approval(
                cluster_id=self.cluster_id,
                decision=self.decision,
                reviewer=None,
                reason=reason,
                source=APPROVAL_SOURCE_TUI,
                feedback_tag=feedback_tag,
            )
        except TuiApiError as exc:
            if self._status is not None:
                self._status.update(f"API rejected the approval: {exc}")
            return
        except Exception as exc:
            if self._status is not None:
                self._status.update(f"Request failed: {exc}")
            return
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


def _app(screen: ModalScreen) -> NengokReviewApp:
    from nengok.tui.app import NengokReviewApp

    app = screen.app
    assert isinstance(app, NengokReviewApp)
    return app
