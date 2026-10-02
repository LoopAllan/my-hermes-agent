"""Gateway watcher that keeps each served profile's opt-in marketplace skills checkout current.

Kept out of the GatewayRunner mixins so the fork touches upstream's runner files with a single
delegating method (``GatewayStartupMixin._marketplace_skills_watcher``).
"""
from __future__ import annotations

import asyncio
import inspect
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


def _bootstrap_profile(home: Path, user_config: Dict[str, Any]) -> None:
    """First clone (and root SOUL.md) for a profile whose checkout does not exist yet.

    Container init bootstraps only the launch home; served profiles that enable a marketplace
    later get their first clone here, inside their own scope.
    """
    from agent.skill_utils import _external_dirs_cache_clear
    from gateway.marketplace_bootstrap import MarketplaceBootstrap
    from gateway.marketplace_config import load_marketplace_config

    settings = load_marketplace_config(user_config, require_bootstrap=True, hermes_home=home)
    if settings is not None:
        MarketplaceBootstrap(home, settings).run()
        _external_dirs_cache_clear()  # discovery cached the root while it was still missing


async def _reload_profile_skills(runner: Any, home: Path, is_launch_home: bool) -> None:
    """Rescan the profile's skills; never re-point an adapter another profile shares.

    The launch (primary) profile reloads as ``/reload-skills`` does. A shared-bot satellite
    rescans in its own scope but refreshes only adapters it owns: its ``_adapters_for_profile``
    view includes the primary's adapter, whose single catalog belongs to the primary profile.
    """
    if is_launch_home:
        await runner._reload_skills_runtime()
        return
    from hermes_constants import profile_name_for_home
    profile = profile_name_for_home(home)
    from agent.skill_commands import reload_skills
    await runner._run_in_executor_with_context(reload_skills)
    shared = {id(adapter) for adapter in (getattr(runner, "adapters", None) or {}).values()}
    for adapter in list(runner._adapters_for_profile(profile).values()):
        refresh = getattr(adapter, "refresh_skill_group", None)
        if id(adapter) in shared or not callable(refresh):
            continue
        try:
            maybe = refresh()
            if inspect.isawaitable(maybe):
                await maybe
        except Exception as exc:
            logger.warning("Adapter %s refresh_skill_group raised: %s", getattr(adapter, "name", adapter), exc)


async def _update_profile(
    runner: Any, home: Path, served_roots: Dict[Path, Path], is_launch_home: bool,
) -> float:
    """Update one profile's marketplace inside its scope; return seconds until it is due again.

    ``served_roots`` remembers each profile's loaded skill root, so disabling the marketplace or
    pointing it elsewhere also reloads (slash-command caches are not keyed by the config).
    """
    from gateway.marketplace_updater import marketplace_config, update_marketplace_worktree
    from gateway.run import _async_profile_runtime_scope
    from hermes_cli.config import load_config_readonly
    async with _async_profile_runtime_scope(home):
        user_config = load_config_readonly()
        settings = marketplace_config(user_config)
        previous_root = served_roots.pop(home, None)
        if not settings:
            if previous_root is not None:
                await _reload_profile_skills(runner, home, is_launch_home)
            return _RECHECK_SECONDS
        served_roots[home] = settings.skills_dir
        if not settings.repo_dir.exists():
            await runner._run_in_executor_with_context(_bootstrap_profile, home, user_config)
            await _reload_profile_skills(runner, home, is_launch_home)
        elif await runner._run_in_executor_with_context(update_marketplace_worktree, user_config) or (
            previous_root is not None and previous_root != settings.skills_dir
        ):
            await _reload_profile_skills(runner, home, is_launch_home)
        return settings.interval_seconds


async def run_marketplace_watcher(runner: Any) -> None:
    """Supervised loop; profiles added by served-profile reconcile are picked up on the next tick."""
    from hermes_constants import get_hermes_home, hermes_home_key
    # Captured outside any profile scope: the home whose adapters are ``runner.adapters``.
    launch_key = hermes_home_key(get_hermes_home())
    next_due: Dict[str, float] = {}
    served_roots: Dict[Path, Path] = {}
    while runner._running:
        for home in _profile_homes(runner):
            key = hermes_home_key(home)
            if time.monotonic() < next_due.get(key, 0.0):
                continue
            try:
                delay = await _update_profile(runner, home, served_roots, key == launch_key)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("marketplace skills watcher failed for %s", home)
                delay = _RECHECK_SECONDS
            next_due[key] = time.monotonic() + delay
        await asyncio.sleep(_TICK_SECONDS)
