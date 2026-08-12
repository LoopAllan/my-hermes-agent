"""Configured fixed phrases for long-running gateway heartbeats."""

from __future__ import annotations

import os
import random


def _working_phases() -> tuple[str, ...]:
    """Return non-empty comma-delimited phrases from the process environment."""
    return tuple(
        phrase.strip()
        for phrase in os.environ.get("HEART_BEAT_WORKING_PHASES", "").split(",")
        if phrase.strip()
    )


async def generate_status_phrase() -> str | None:
    """Pick a configured user-facing heartbeat phrase, if configured."""
    phases = _working_phases()
    return random.choice(phases) if phases else None
