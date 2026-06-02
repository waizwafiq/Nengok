"""
Textual-based terminal UI for VPS operators who run Nengok over SSH.

The TUI talks to the same FastAPI server the browser dashboard uses, so
the wire format and the audit-log rows stay consistent across surfaces.
The package gates on the optional `tui` extra (`pip install
"nengok[tui]"`); a bare install raises `OptionalDependencyError` when
`nengok review` is invoked.
"""

from __future__ import annotations
