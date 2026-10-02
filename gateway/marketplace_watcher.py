"""Gateway watcher that keeps each served profile's opt-in marketplace skills checkout current.

Kept out of the GatewayRunner mixins so the fork touches upstream's runner files with a single
delegating method (``GatewayStartupMixin._marketplace_skills_watcher``).
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Shortest allowed ``skills.marketplace.interval_seconds``; disabled or invalid profiles are re-read
# every _RECHECK_SECONDS so enabling a marketplace takes effect without a restart.
_TICK_SECONDS = 30
_RECHECK_SECONDS = 300


def _profile_homes(runner: Any) -> List[Path]:
    """The launch home plus every served profile home (multiplex), deduplicated."""
    from hermes_constants import get_hermes_home, hermes_home_key
    homes: Dict[str, Path] = {}
    for home in (get_hermes_home(), *(getattr(runner, "_served_profile_homes", None) or {}).values()):
        homes.setdefault(hermes_home_key(home), Path(home))
    return list(homes.values())


async def _update_profile(runner: Any, home: Path) -> float:
    """Update one profile's marketplace inside its scope; return seconds until it is due again."""
    from gateway.marketplace_updater import marketplace_config, update_marketplace_worktree
    from gateway.run import _async_profile_runtime_scope
    from hermes_cli.config import load_config_readonly
    async with _async_profile_runtime_scope(home):
        user_config = load_config_readonly()
        settings = marketplace_config(user_config)
        if not settings:
            return _RECHECK_SECONDS
        if await runner._run_in_executor_with_context(update_marketplace_worktree, user_config):
            await runner._reload_skills_runtime()
        return settings.interval_seconds


async def run_marketplace_watcher(runner: Any) -> None:
    """Supervised loop; profiles added by served-profile reconcile are picked up on the next tick."""
    from hermes_constants import hermes_home_key
    next_due: Dict[str, float] = {}
    while runner._running:
        for home in _profile_homes(runner):
            key = hermes_home_key(home)
            if time.monotonic() < next_due.get(key, 0.0):
                continue
            try:
                delay = await _update_profile(runner, home)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("marketplace skills watcher failed for %s", home)
                delay = _RECHECK_SECONDS
            next_due[key] = time.monotonic() + delay
        await asyncio.sleep(_TICK_SECONDS)
