"""Load a Notifier from a dotted-path spec.

Same contract as nengok.runners.loader: ``module.path:ClassName``, instantiated
with kwargs, runtime-checked against the Notifier protocol, and name-asserted
so the registry key and instance.name are always identical.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from nengok.errors import NotifierLoadError
from nengok.notifiers.protocol import Notifier


def load_notifier(spec: str, kwargs: dict[str, Any] | None = None, *, registry_key: str) -> Notifier:
    """Import, instantiate, and validate the notifier referenced by ``spec``."""
    module_part, _, class_part = spec.partition(":")
    if not module_part or not class_part or ":" in class_part:
        raise NotifierLoadError(
            f"Notifier spec '{spec}' is malformed. "
            "Expected `module.path:ClassName` (e.g. `nengok.notifiers.slack.notifier:SlackNotifier`).",
            notifier_name=registry_key,
        )

    try:
        module = import_module(module_part)
    except ImportError as exc:
        raise NotifierLoadError(
            f"Could not import module `{module_part}` for notifier '{registry_key}'. "
            "Confirm the package is installed in the same venv as Nengok. "
            f"Underlying error: {exc}",
            notifier_name=registry_key,
        ) from exc

    try:
        notifier_cls = getattr(module, class_part)
    except AttributeError as exc:
        raise NotifierLoadError(
            f"Module `{module_part}` does not define `{class_part}` for notifier '{registry_key}'.",
            notifier_name=registry_key,
        ) from exc

    init_kwargs = kwargs or {}
    try:
        instance = notifier_cls(**init_kwargs)
    except TypeError as exc:
        raise NotifierLoadError(
            f"Failed to construct `{class_part}` for notifier '{registry_key}' "
            f"with kwargs {list(init_kwargs)!r}: {exc}.",
            notifier_name=registry_key,
        ) from exc

    if not isinstance(instance, Notifier):
        missing = _missing_members(instance)
        detail = (
            f"`{class_part}` is missing: {', '.join(missing)}."
            if missing
            else f"`{class_part}` does not satisfy the Notifier protocol."
        )
        raise NotifierLoadError(
            f"{detail} A Notifier must expose `name`, `notify_fix_proposed`, " "and `notify_escalation`.",
            notifier_name=registry_key,
        )

    if instance.name != registry_key:
        raise NotifierLoadError(
            f"Notifier loaded under registry key '{registry_key}' returned "
            f"name='{instance.name}'. Registry key and instance.name must match "
            "for stable deduplication keys in nengok_notifications.",
            notifier_name=registry_key,
        )

    return instance


def _missing_members(instance: object) -> list[str]:
    missing = []
    if not hasattr(instance, "name"):
        missing.append("`name` property")
    if not callable(getattr(instance, "notify_fix_proposed", None)):
        missing.append("`notify_fix_proposed` method")
    if not callable(getattr(instance, "notify_escalation", None)):
        missing.append("`notify_escalation` method")
    return missing
