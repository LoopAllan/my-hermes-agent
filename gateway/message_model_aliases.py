"""Resolve declarative, per-message gateway model aliases."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import logging
import re
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MessageModelAlias:
    """A configured alias that selects a model for the current agent turn."""

    alias: str
    model: str
    # Optional: route this turn through another provider, like ``channel_overrides``.
    provider: Optional[str] = None


def resolve_message_model_alias(
    user_message: str | None,
    config: dict[str, Any] | None,
) -> MessageModelAlias | None:
    """Return the first configured alias present as a complete word.

    The mapping lives at ``model.message_aliases`` as ``{alias: {model: ..., provider: ...}}``
    (``provider`` optional: without it only the model changes on the current route).  Mapping order is the
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
            provider = entry.get("provider")
            provider = provider.strip() if isinstance(provider, str) and provider.strip() else None
            return MessageModelAlias(alias=alias, model=model.strip(), provider=provider)
    return None


def _provider_route(match: MessageModelAlias) -> tuple[str, dict]:
    from gateway.run import _resolve_runtime_agent_kwargs_for_provider
    routed = _resolve_runtime_agent_kwargs_for_provider(match.provider, target_model=match.model)
    routed.pop("model", None)
    return match.model, routed


def apply_message_model_alias(
    user_message: Optional[str], model: str, runtime_kwargs: dict, config: Optional[dict],
) -> tuple[str, dict]:
    """Model and route for this turn only, never the session or persisted config.

    An alias naming a ``provider`` gets that provider's whole route (as ``channel_overrides`` do);
    an unavailable provider keeps this turn on the current route.
    """
    match = resolve_message_model_alias(user_message, config)
    if match is None:
        return model, runtime_kwargs
    if not match.provider:
        return match.model, runtime_kwargs
    try:
        return _provider_route(match)
    except Exception as exc:
        logger.warning("Model alias %s provider %s unavailable: %s", match.alias, match.provider, exc)
        return model, runtime_kwargs


def resolve_turn_model_route(
    runner: Any, user_message: Optional[str], *, source: Any, session_key: Optional[str],
    user_config: Optional[dict],
) -> tuple[str, dict, bool]:
    """``(model, runtime_kwargs, alias_applied)`` for one turn: the session route plus any alias.

    When the session route cannot resolve (e.g. expired default credentials), an alias naming its
    own provider still answers; otherwise the original resolution error propagates unchanged.
    """
    try:
        model, runtime_kwargs = runner._resolve_session_agent_runtime(
            source=source, session_key=session_key, user_config=user_config,
        )
    except Exception:
        match = resolve_message_model_alias(user_message, user_config)
        if match is None or not match.provider:
            raise
        try:
            routed_model, routed_runtime = _provider_route(match)
        except Exception as alias_exc:
            logger.warning("Model alias %s provider %s unavailable: %s", match.alias, match.provider, alias_exc)
            raise
        runner._pre_agent_fallback_notice = None
        return routed_model, routed_runtime, True
    resolved_model, resolved_runtime = apply_message_model_alias(user_message, model, runtime_kwargs, user_config)
    return resolved_model, resolved_runtime, (resolved_model, resolved_runtime) != (model, runtime_kwargs)


# What the user typed, keyed by routed profile + conversation + inbound message id (ids repeat across
# chats, and two profiles' bots can see the same chat),
# captured before skill scaffolds or media enrichment rewrite ``event.text``. A small LRU, so
# re-resolving within one turn sees the same text.
_USER_AUTHORED_TEXT: "OrderedDict[tuple, str]" = OrderedDict()
_USER_AUTHORED_TEXT_LIMIT = 512
_USER_AUTHORED_TEXT_LOCK = threading.Lock()


def _text_key(source: Any, message_id: Any) -> tuple:
    platform = getattr(source, "platform", None)
    return (
        getattr(source, "profile", None), getattr(platform, "value", platform),
        getattr(source, "chat_id", None), getattr(source, "thread_id", None), str(message_id),
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
