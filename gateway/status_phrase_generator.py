"""Configured fixed phrases for long-running gateway heartbeats."""

from __future__ import annotations

import os
import random
from collections.abc import Mapping

_INTERNAL_PHRASES_ENV = "HEART_BEAT_WORKING_PHASES"


def _split_phrases(value: str) -> tuple[str, ...]:
    """Return non-empty comma-delimited phrases."""
    return tuple(phrase.strip() for phrase in value.split(",") if phrase.strip())


def _working_phrases() -> tuple[str, ...]:
    """Resolve public config, allowing an internal deployment env override."""
    if _INTERNAL_PHRASES_ENV in os.environ:
        return _split_phrases(os.environ[_INTERNAL_PHRASES_ENV])

    try:
        from gateway.status_phrases import resolve_status_phrase_catalog
        from hermes_cli.config import load_config

        config = load_config()
        display = config.get("display") if isinstance(config, Mapping) else None
        if not isinstance(display, Mapping) or "status_phrases" not in display:
            return ()
        return tuple(resolve_status_phrase_catalog(config).get("status", ()))
    except Exception:
        return ()


async def generate_status_phrase() -> str | None:
    """Pick a configured user-facing heartbeat phrase, if configured."""
    phrases = _working_phrases()
    return random.choice(phrases) if phrases else None
