"""Safe in-process updater for a configured external-skills Git worktree."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

from gateway.marketplace_config import (
    MarketplaceConfig,
    MarketplaceConfigError,
    load_marketplace_config,
)
from gateway.marketplace_credentials import GitAuthEnvironment, marketplace_git_env

logger = logging.getLogger(__name__)


def marketplace_config(config: dict[str, Any]) -> MarketplaceConfig | None:
    """Return shared validated settings, logging invalid updater configuration."""
    try:
        return load_marketplace_config(config)
    except MarketplaceConfigError as exc:
        logger.warning("invalid marketplace sync configuration: %s", exc)
        return None


def _git_env() -> dict[str, str]:
    """Environment for the plain (unauthenticated) git child processes."""
    return marketplace_git_env()


def _git(repo: Path, *args: str) -> str:
    env = _git_env()
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
    env = _git_env()
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


def _normalized_remote(url: str) -> str:
    url = url.strip().rstrip("/")
    return url[:-4] if url.endswith(".git") else url


def _remote_is_configured_repository(repo: Path, remote: str, repository: str) -> bool:
    """The fetch carries the Vault token, so its target must be the configured repository.

    ``git remote get-url`` applies ``insteadOf`` rewrites, i.e. it names where Git will connect;
    a ``.git/config`` edited to point elsewhere leaves ``git status`` clean, so check it here.
    """
    if not repository:
        return False
    try:
        effective = _git(repo, "remote", "get-url", remote)
    except subprocess.CalledProcessError:
        return False
    return _normalized_remote(effective) == _normalized_remote(repository)


def _skills_root_is_tree(repo: Path, revision: str, skills_path: Path) -> bool:
    """True when ``skills_path`` is a directory in ``revision``'s own tree.

    Bootstrap validates containment once; a later fast-forward could turn the root (or a parent)
    into a symlink that discovery would follow out of the checkout. ``rev:path`` lookup never
    traverses a symlink entry, so anything but ``tree`` means the root left the repository.
    """
    try:
        kind = _git(repo, "cat-file", "-t", f"{revision}:{skills_path.as_posix()}")
    except subprocess.CalledProcessError:
        return False
    return kind == "tree"


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
        if not _remote_is_configured_repository(repo, settings.remote, settings.repository):
            logger.warning(
                "marketplace remote %r is not skills.marketplace.repository; refusing authenticated fetch",
                settings.remote,
            )
            return False
        _fetch(repo, settings.remote, settings.branch)
        target = _git(repo, "rev-parse", "FETCH_HEAD")
        current = _git(repo, "rev-parse", "HEAD")
        if target == current:
            return False
        if _is_ancestor(repo, current, target):
            if not _skills_root_is_tree(repo, target, settings.skills_path):
                logger.warning(
                    "marketplace update %s does not keep %s a real directory; refusing update",
                    target, settings.skills_path,
                )
                return False
            _git(repo, "merge", "--ff-only", target)
            logger.info("marketplace advanced to %s", target)
            return True
        logger.warning("marketplace checkout diverged; refusing update")
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        logger.warning("marketplace update failed: %s", exc)
    return False
