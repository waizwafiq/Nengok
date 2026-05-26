"""
Scrub PII from span text before it leaves the local process.

The redactor sits in front of every Gemini call site that includes span
content (input/output values, exemplar bodies) and in front of the
artifact writer that persists RCA bundles. Regex-based redaction is
best-effort and not a SOC2 control. Teams with strict requirements can
swap in their own callable via `config.redactor_callable`.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from nengok.config import NengokConfig


class RedactionRule(BaseModel):
    """One named regex substitution applied to span text."""

    name: str
    pattern: str
    replacement: str


DEFAULT_RULES: list[RedactionRule] = [
    RedactionRule(
        name="email",
        pattern=r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        replacement="<redacted-email>",
    ),
    RedactionRule(
        name="google_api_key",
        pattern=r"AIza[a-zA-Z0-9_\-]{35}",
        replacement="<redacted-google-api-key>",
    ),
    RedactionRule(
        name="aws_access_key",
        pattern=r"AKIA[0-9A-Z]{16}",
        replacement="<redacted-aws-key>",
    ),
    RedactionRule(
        name="bearer_token",
        pattern=r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=\-]{8,}",
        replacement=r"\1 <redacted-token>",
    ),
    RedactionRule(
        name="password_field",
        pattern=r"(?i)\b(password|secret)\s*[=:]\s*\S+",
        replacement=r"\1=<redacted>",
    ),
    RedactionRule(
        name="credit_card",
        pattern=r"\b(?:\d[ \-]?){15,18}\d\b",
        replacement="<redacted-cc>",
    ),
    RedactionRule(
        name="ssn",
        pattern=r"\b\d{3}-\d{2}-\d{4}\b",
        replacement="<redacted-ssn>",
    ),
    RedactionRule(
        name="us_phone",
        pattern=(r"(?<!\d)(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\d)"),
        replacement="<redacted-phone>",
    ),
    RedactionRule(
        name="ipv4",
        pattern=r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        replacement="<redacted-ipv4>",
    ),
    RedactionRule(
        name="ipv6",
        pattern=r"\b(?:[A-Fa-f0-9]{1,4}:){2,7}(?::?[A-Fa-f0-9]{0,4})\b",
        replacement="<redacted-ipv6>",
    ),
]


DEFAULT_RULE_NAMES: list[str] = [rule.name for rule in DEFAULT_RULES]


RedactFn = Callable[[str], str]


@dataclass
class Redactor:
    """Apply an ordered list of redaction rules to arbitrary text."""

    rules: list[RedactionRule] = field(default_factory=list)
    custom_fn: RedactFn | None = None

    def __post_init__(self) -> None:
        self._compiled: list[tuple[re.Pattern[str], str]] = [
            (re.compile(rule.pattern), rule.replacement) for rule in self.rules
        ]

    def redact(self, text: str | None) -> str:
        """Return ``text`` with the configured rules (or custom callable) applied."""
        if not text:
            return text or ""
        if self.custom_fn is not None:
            return self.custom_fn(text)
        out = text
        for pattern, replacement in self._compiled:
            out = pattern.sub(replacement, out)
        return out

    @classmethod
    def from_config(cls, config: NengokConfig) -> Redactor:
        """Build a redactor from `NengokConfig`, merging defaults with user rules."""
        if not config.redaction_enabled:
            return cls(rules=[])

        if config.redactor_callable:
            return cls(rules=[], custom_fn=_load_callable_redactor(config.redactor_callable))

        enabled_default_names = set(
            config.redaction_default_rules
            if config.redaction_default_rules is not None
            else DEFAULT_RULE_NAMES
        )
        defaults = [rule for rule in DEFAULT_RULES if rule.name in enabled_default_names]
        user_rules = [_coerce_rule(item) for item in (config.redaction_rules or [])]
        return cls(rules=defaults + user_rules)


def _coerce_rule(item: RedactionRule | dict[str, str]) -> RedactionRule:
    if isinstance(item, RedactionRule):
        return item
    return RedactionRule(**item)


def _load_callable_redactor(dotted_path: str) -> RedactFn:
    """Resolve `module.path:callable_name` into the callable itself."""
    if ":" not in dotted_path:
        raise ValueError(
            f"redactor_callable '{dotted_path}' is malformed. "
            "Expected `module.path:callable_name` "
            "(e.g. `mycorp.scrubbers:enterprise_scrubber`)."
        )
    module_part, attr_part = dotted_path.split(":", 1)
    module = importlib.import_module(module_part)
    attr = getattr(module, attr_part, None)
    if attr is None or not callable(attr):
        raise ValueError(
            f"redactor_callable '{dotted_path}' did not resolve to a callable. "
            f"Confirm `{attr_part}` exists in `{module_part}` and accepts a single `str`."
        )
    return attr
