"""Shared parsing and validation for the configured skills marketplace."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


class MarketplaceConfigError(ValueError):
    """Raised when an enabled marketplace configuration is invalid."""


@dataclass(frozen=True)
class MarketplaceConfig:
    """Validated marketplace settings consumed by bootstrap and updates."""

    repository: str
    repo_dir: Path
    skills_path: Path
    remote: str
    branch: str
    interval_seconds: int


def _single_line_string(settings: Mapping[str, Any], field: str, default: str = "") -> str:
    value = settings.get(field, default)
    if not isinstance(value, str) or any(char in value for char in "\r\n\x00"):
        raise MarketplaceConfigError(
            f"skills.marketplace.{field} must be a nonempty single-line string"
        )
    value = value.strip()
    if not value:
        raise MarketplaceConfigError(
            f"skills.marketplace.{field} must be a nonempty single-line string"
        )
    return value


def load_marketplace_config(
    config: Mapping[str, Any], *, require_bootstrap: bool = False
) -> MarketplaceConfig | None:
    """Load marketplace settings from the full user configuration.

    Disabled or absent settings are an intentional no-op. Enabled settings are
    validated once here for both the initial clone and in-process updater.
    """
    skills = config.get("skills") or {}
    if not isinstance(skills, Mapping):
        raise MarketplaceConfigError("skills must be a mapping")
    settings = skills.get("marketplace") or {}
    if not isinstance(settings, Mapping):
        raise MarketplaceConfigError("skills.marketplace must be a mapping")
    if settings.get("enabled") is not True:
        return None

    repo_dir_value = _single_line_string(settings, "repo_dir")
    remote = _single_line_string(settings, "remote", "origin").strip()
    branch = _single_line_string(settings, "branch", "main").strip()
    if remote.startswith("-") or branch.startswith("-"):
        raise MarketplaceConfigError(
            "skills.marketplace remote and branch must be non-option names"
        )

    interval_value = settings.get("interval_seconds", 300)
    try:
        interval_seconds = max(30, int(interval_value))
    except (TypeError, ValueError) as exc:
        raise MarketplaceConfigError(
            "skills.marketplace.interval_seconds must be an integer"
        ) from exc

    repository = settings.get("repository", "")
    if require_bootstrap:
        repository = _single_line_string(settings, "repository")
    elif not isinstance(repository, str) or any(char in repository for char in "\r\n\x00"):
        raise MarketplaceConfigError(
            "skills.marketplace.repository must be a single-line string"
        )

    skills_value = settings.get("skills_path", "plugins/skills")
    if require_bootstrap:
        skills_value = _single_line_string(settings, "skills_path", "plugins/skills")
    elif not isinstance(skills_value, str) or not skills_value:
        skills_value = "plugins/skills"
    skills_path = Path(skills_value)
    if skills_path.is_absolute() or ".." in skills_path.parts:
        raise MarketplaceConfigError(
            "skills.marketplace.skills_path must stay within the repository"
        )

    expanded_repo_dir = os.path.expandvars(os.path.expanduser(repo_dir_value))
    return MarketplaceConfig(
        repository=repository,
        repo_dir=Path(expanded_repo_dir),
        skills_path=skills_path,
        remote=remote,
        branch=branch,
        interval_seconds=interval_seconds,
    )


def load_marketplace_config_file(
    hermes_home: Path, *, require_bootstrap: bool = False
) -> MarketplaceConfig | None:
    """Read marketplace settings from ``HERMES_HOME/config.yaml`` only.

    Goes through ``read_user_config_raw`` rather than a bare ``yaml.safe_load``:
    it is the canonical primitive for reading one user ``config.yaml`` exactly
    as written, and raw reads outside the loader-owning modules are rejected by
    ``tests/hermes_cli/test_config_read_guard.py``. The unmerged semantics this
    function documents are preserved — no DEFAULT_CONFIG merge, no managed
    overlay, no ``${ENV_VAR}`` expansion.

    A missing file is checked explicitly, because the primitive reports it as
    ``{}`` and this function's callers need it to fail loudly. A root that is
    not a mapping likewise reads as ``{}`` rather than raising here; it still
    fails whenever the caller passes ``require_bootstrap=True``, since an empty
    mapping has no repository.
    """
    from hermes_cli.config import read_user_config_raw

    config_path = hermes_home / "config.yaml"
    if not config_path.is_file():
        raise MarketplaceConfigError(
            f"cannot read config.yaml: {config_path} is not a readable file"
        )
    try:
        config = read_user_config_raw(config_path)
    except (OSError, yaml.YAMLError) as exc:
        raise MarketplaceConfigError(f"cannot read config.yaml: {exc}") from exc
    return load_marketplace_config(config, require_bootstrap=require_bootstrap)
