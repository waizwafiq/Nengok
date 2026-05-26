"""
Confirm Gemini accepts the configured key with a one-token ping.

The probe reuses `nengok.init_wizard.probe_gemini` so the same fake
covers both the wizard's pre-write gate and the post-install doctor
check. Latency is measured so a slow Gemini region surfaces in the
doctor report without forcing the user to time things by hand.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from nengok.config import NengokConfig
from nengok.diagnostics.base import ProbeResult, ProbeStatus
from nengok.init_wizard import probe_gemini as wizard_probe_gemini


def probe_gemini(
    config: NengokConfig,
    *,
    ping: Callable[[str], None] | None = None,
) -> ProbeResult:
    api_key = config.google_api_key
    if not api_key:
        return ProbeResult(
            name="gemini",
            status=ProbeStatus.FAIL,
            detail="GOOGLE_API_KEY is not set",
            fix_hint=(
                "Run `export GOOGLE_API_KEY=<key>` or add `google_api_key` "
                "to ~/.nengok/config.toml. Get a key at "
                "https://aistudio.google.com/app/apikey."
            ),
        )

    started = time.monotonic()
    result = wizard_probe_gemini(api_key=api_key, ping=ping)
    elapsed_ms = int((time.monotonic() - started) * 1000)

    if not result.ok:
        return ProbeResult(
            name="gemini",
            status=ProbeStatus.FAIL,
            detail=result.detail,
            fix_hint=result.fix_hint,
        )
    return ProbeResult(
        name="gemini",
        status=ProbeStatus.OK,
        detail=f"{config.diagnoser_model} (auth OK, {elapsed_ms}ms ping)",
    )
