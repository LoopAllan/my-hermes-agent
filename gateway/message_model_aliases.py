"""Resolve declarative, per-message gateway model aliases."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import re
import threading
from typing import Any, Optional


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


# What the user typed, keyed by conversation + inbound message id (platform ids repeat across chats),
# captured before skill scaffolds or media enrichment rewrite ``event.text``. A small LRU, so
# re-resolving within one turn sees the same text.
_USER_AUTHORED_TEXT: "OrderedDict[tuple, str]" = OrderedDict()
_USER_AUTHORED_TEXT_LIMIT = 512
_USER_AUTHORED_TEXT_LOCK = threading.Lock()


def _text_key(source: Any, message_id: Any) -> tuple:
    platform = getattr(source, "platform", None)
    return (
        getattr(platform, "value", platform), getattr(source, "chat_id", None),
        getattr(source, "thread_id", None), str(message_id),
    )


def remember_user_authored_text(event: Any) -> None:
    """Record an admitted event's own text so alias matching never sees expanded content."""
    message_id, text = getattr(event, "message_id", None), getattr(event, "text", None)
    if not message_id or not isinstance(text, str) or getattr(event, "internal", False):
        return
    key = _text_key(getattr(event, "source", None), message_id)
    with _USER_AUTHORED_TEXT_LOCK:
        _USER_AUTHORED_TEXT[key] = text
        _USER_AUTHORED_TEXT.move_to_end(key)
        while len(_USER_AUTHORED_TEXT) > _USER_AUTHORED_TEXT_LIMIT:
            _USER_AUTHORED_TEXT.popitem(last=False)


def user_authored_text(
    source: Any, inbound_message_id: Optional[str], fallback: Optional[str]
) -> Optional[str]:
    """The recorded user text for this conversation's turn, or ``fallback`` when none was captured."""
    if not inbound_message_id:
        return fallback
    with _USER_AUTHORED_TEXT_LOCK:
        return _USER_AUTHORED_TEXT.get(_text_key(source, inbound_message_id), fallback)
