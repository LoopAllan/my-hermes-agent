"""Resolve declarative, per-message gateway model aliases."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class MessageModelAlias:
    """A configured alias that selects a model for the current agent turn."""

    alias: str
    model: str


def resolve_message_model_alias(
    user_message: str | None,
    config: dict[str, Any] | None,
) -> MessageModelAlias | None:
    """Return the first configured alias present as a complete word.

    The mapping lives at ``model.message_aliases``.  Mapping order is the
    precedence order when a message deliberately includes more than one alias.
    Aliases are case-insensitive and use escaped ``\b`` boundaries, so an alias
    such as ``Sol`` matches ``"use Sol"`` but never the ``sol`` in ``"console"``.
    Invalid config entries fail closed instead of affecting model selection.
    """
    if not isinstance(user_message, str) or not user_message:
        return None
    model_config = config.get("model") if isinstance(config, dict) else None
    aliases = model_config.get("message_aliases") if isinstance(model_config, dict) else None
    if not isinstance(aliases, dict):
        return None

    for raw_alias, entry in aliases.items():
        alias = str(raw_alias).strip() if isinstance(raw_alias, str) else ""
        model = entry.get("model") if isinstance(entry, dict) else None
        if not alias or not isinstance(model, str) or not model.strip():
            continue
        if re.search(rf"\b{re.escape(alias)}\b", user_message, flags=re.IGNORECASE):
            return MessageModelAlias(alias=alias, model=model.strip())
    return None
