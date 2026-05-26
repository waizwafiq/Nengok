"""
Per-cycle Gemini token and dollar accounting.

The orchestrator holds one `CostTracker` per cycle. Every `call_gemini`
invocation feeds prompt and completion token counts back into the
tracker, and the orchestrator checks `is_over_budget(...)` between
stages so a runaway cluster cannot blow through the user's monthly
Gemini cap inside a single watch tick.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CostTracker:
    """
    Running totals for one cycle's Gemini spend.

    `input_dollars_per_million` and `output_dollars_per_million` are
    the configured per-token rates. The defaults match gemini-3.1-pro
    list pricing; cheaper models override via `NengokConfig`.
    """

    input_dollars_per_million: float = 6.0
    output_dollars_per_million: float = 24.0
    _prompt_tokens: int = field(default=0, init=False)
    _completion_tokens: int = field(default=0, init=False)

    def record(self, prompt_tokens: int, completion_tokens: int) -> None:
        if prompt_tokens < 0 or completion_tokens < 0:
            raise ValueError("token counts must be non-negative")
        self._prompt_tokens += prompt_tokens
        self._completion_tokens += completion_tokens

    @property
    def tokens_used(self) -> int:
        return self._prompt_tokens + self._completion_tokens

    @property
    def prompt_tokens(self) -> int:
        return self._prompt_tokens

    @property
    def completion_tokens(self) -> int:
        return self._completion_tokens

    @property
    def dollars_used(self) -> float:
        input_cost = self._prompt_tokens * self.input_dollars_per_million / 1_000_000
        output_cost = self._completion_tokens * self.output_dollars_per_million / 1_000_000
        return input_cost + output_cost

    def reset(self) -> None:
        self._prompt_tokens = 0
        self._completion_tokens = 0

    def is_over_budget(self, limit_tokens: int) -> bool:
        if limit_tokens <= 0:
            return False
        return self.tokens_used > limit_tokens
