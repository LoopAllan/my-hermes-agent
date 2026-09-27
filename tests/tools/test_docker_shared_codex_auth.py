"""Contract tests for Docker's shared Codex auth mount.

The hosted/profile-deployment layout keeps each profile's Hermes home mounted
at /opt/data, while sharing Codex CLI auth through a separate mount. These
static tests guard the container/deployment contracts without requiring Docker.
"""

from __future__ import annotations

from pathlib import Path

import hermes_yaml as yaml


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


def test_stage2_hook_preserves_the_root_owned_codex_rules_artifact() -> None:
    hook = STAGE2_HOOK.read_text(encoding="utf-8")

    assert 'CODEX_HOME="${CODEX_HOME:-/etc/data/codex}"' in hook
    assert 'mkdir -p "$CODEX_HOME"' in hook
    assert 'chown_hermes_tree "$CODEX_HOME"' not in hook
    assert 'find "$CODEX_HOME" -mindepth 1 -maxdepth 1 ! -name AGENTS.md' in hook
    assert 'chown root:root "$CODEX_HOME/AGENTS.md"' in hook
    assert 'chmod 0444 "$CODEX_HOME/AGENTS.md"' in hook
    assert 'chown root:hermes "$CODEX_HOME"' in hook
    assert 'chmod 1770 "$CODEX_HOME"' in hook
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
        assert "${HERMES_SHARED_CODEX_DIR:-~/.codex}/auth.json:/etc/data/codex/auth.json" in volumes
        assert "${HERMES_SHARED_CODEX_DIR:-~/.codex}:/etc/data/codex" not in volumes
        assert "CODEX_HOME=/etc/data/codex" in environment


def test_windows_compose_mounts_profile_data_and_shared_codex_auth_separately() -> None:
    compose = _load_compose(COMPOSE_WINDOWS)

    for service_name in ("gateway", "dashboard"):
        service = compose["services"][service_name]
        volumes = service.get("volumes", [])
        environment = service.get("environment", [])

        assert "${HERMES_PROFILE_DATA:-${USERPROFILE}/.hermes}:/opt/data" in volumes
        assert "${HERMES_SHARED_CODEX_DIR:-${USERPROFILE}/.codex}/auth.json:/etc/data/codex/auth.json" in volumes
        assert "${HERMES_SHARED_CODEX_DIR:-${USERPROFILE}/.codex}:/etc/data/codex" not in volumes
        assert "CODEX_HOME=/etc/data/codex" in environment
