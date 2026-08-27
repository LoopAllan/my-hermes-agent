"""Safe in-process updater for a configured external-skills Git worktree."""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from gateway.marketplace_config import (
    MarketplaceConfig,
    MarketplaceConfigError,
    load_marketplace_config,
)
from gateway.marketplace_credentials import GitAuthEnvironment

logger = logging.getLogger(__name__)


def marketplace_config(config: dict[str, Any]) -> MarketplaceConfig | None:
    """Return shared validated settings, logging invalid updater configuration."""
    try:
        return load_marketplace_config(config)
    except MarketplaceConfigError as exc:
        logger.warning("invalid marketplace sync configuration: %s", exc)
        return None


def _git(repo: Path, *args: str) -> str:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        timeout=30,
        check=True,
        env=env,
    )
    return result.stdout.strip()


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", ancestor, descendant],
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
        env=env,
    )
    if result.returncode not in (0, 1):
        raise subprocess.CalledProcessError(
            result.returncode, result.args, result.stdout, result.stderr
        )
    return result.returncode == 0


def _fetch(repo: Path, remote: str, branch: str) -> None:
    with GitAuthEnvironment.from_vault() as env:
        subprocess.run(
            ["git", "-C", str(repo), "fetch", "--no-tags", remote, branch],
            text=True,
            capture_output=True,
            timeout=30,
            check=True,
            env=env,
        )


def update_marketplace_worktree(config: dict[str, Any]) -> bool:
    """Fast-forward an allowed external skill checkout; never overwrite local state."""
    settings = marketplace_config(config)
    if not settings:
        return False
    try:
        from agent.skill_utils import get_external_skills_dirs

        repo = settings.repo_dir.expanduser().resolve()
        allowed = {path.resolve() for path in get_external_skills_dirs()}
        if not any(repo == path or repo in path.parents for path in allowed):
            logger.warning(
                "marketplace repo_dir does not contain an external skill directory: %s",
                repo,
            )
            return False
        if _git(repo, "status", "--porcelain"):
            logger.warning("marketplace checkout is dirty; refusing update")
            return False
        _fetch(repo, settings.remote, settings.branch)
        target = _git(repo, "rev-parse", "FETCH_HEAD")
        current = _git(repo, "rev-parse", "HEAD")
        if target == current:
            return False
        if _is_ancestor(repo, current, target):
            _git(repo, "merge", "--ff-only", target)
            logger.info("marketplace advanced to %s", target)
            return True
        logger.warning("marketplace checkout diverged; refusing update")
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        logger.warning("marketplace update failed: %s", exc)
    return False
