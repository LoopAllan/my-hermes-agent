"""Contract tests for Docker's shared Codex auth mount.

The hosted/profile-deployment layout keeps each profile's Hermes home mounted
at /opt/data, while sharing Codex CLI auth through a separate mount. These
static tests guard the container/deployment contracts without requiring Docker.
"""

from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"
STAGE2_HOOK = REPO_ROOT / "docker" / "stage2-hook.sh"
COMPOSE = REPO_ROOT / "docker-compose.yml"
COMPOSE_WINDOWS = REPO_ROOT / "docker-compose.windows.yml"


def test_docker_image_defaults_codex_home_to_shared_mount() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "ENV CODEX_HOME=/etc/data/codex" in dockerfile, (
        "Docker image should default Codex CLI auth to a mount outside /opt/data "
        "so /opt/data can remain the per-profile Hermes home."
    )


def test_stage2_hook_bootstraps_shared_codex_home_outside_hermes_home() -> None:
    hook = STAGE2_HOOK.read_text(encoding="utf-8")

    assert 'CODEX_HOME="${CODEX_HOME:-/etc/data/codex}"' in hook
    assert 'mkdir -p "$CODEX_HOME"' in hook
    assert 'chown_hermes_tree "$CODEX_HOME"' in hook
    assert 'as_hermes mkdir -p \\' in hook
    assert '    "$CODEX_HOME" \\' in hook


def _load_compose(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_linux_compose_mounts_profile_data_and_shared_codex_auth_separately() -> None:
    compose = _load_compose(COMPOSE)

    for service_name in ("gateway", "dashboard"):
        service = compose["services"][service_name]
        volumes = service.get("volumes", [])
        environment = service.get("environment", [])

        assert "${HERMES_PROFILE_DATA:-~/.hermes}:/opt/data" in volumes
        assert "${HERMES_SHARED_CODEX_DIR:-~/.codex}:/etc/data/codex" in volumes
        assert "CODEX_HOME=/etc/data/codex" in environment


def test_windows_compose_mounts_profile_data_and_shared_codex_auth_separately() -> None:
    compose = _load_compose(COMPOSE_WINDOWS)

    for service_name in ("gateway", "dashboard"):
        service = compose["services"][service_name]
        volumes = service.get("volumes", [])
        environment = service.get("environment", [])

        assert "${HERMES_PROFILE_DATA:-${USERPROFILE}/.hermes}:/opt/data" in volumes
        assert "${HERMES_SHARED_CODEX_DIR:-${USERPROFILE}/.codex}:/etc/data/codex" in volumes
        assert "CODEX_HOME=/etc/data/codex" in environment
