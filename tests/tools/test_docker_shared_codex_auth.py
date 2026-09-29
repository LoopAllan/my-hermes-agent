"""Contracts separating Allan's shared Codex runtime from the core image."""

from __future__ import annotations

from pathlib import Path

import hermes_yaml as yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "Dockerfile"
STAGE2_HOOK = REPO_ROOT / "docker" / "stage2-hook.sh"
COMPOSE = REPO_ROOT / "docker-compose.yml"
COMPOSE_WINDOWS = REPO_ROOT / "docker-compose.windows.yml"
ALLAN_HOOK = REPO_ROOT / "docker" / "allan" / "codex-init-hook.sh"


def _load_compose(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_core_image_has_no_allan_shared_codex_runtime_contract() -> None:
    """The reusable core must not own Allan's shared OAuth state."""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    hook = STAGE2_HOOK.read_text(encoding="utf-8")

    assert "ENV CODEX_HOME=/etc/data/codex" not in dockerfile
    assert "/etc/data/codex" not in dockerfile
    assert "CODEX_HOME" not in hook


def test_core_compose_examples_do_not_mount_allan_shared_codex_auth() -> None:
    """Generic Compose examples retain only their per-profile Hermes home."""
    for path, profile_mount in (
        (COMPOSE, "${HERMES_PROFILE_DATA:-~/.hermes}:/opt/data"),
        (COMPOSE_WINDOWS, "${HERMES_PROFILE_DATA:-${USERPROFILE}/.hermes}:/opt/data"),
    ):
        compose = _load_compose(path)
        for service_name in ("gateway", "dashboard"):
            service = compose["services"][service_name]
            volumes = service.get("volumes", [])
            environment = service.get("environment", [])

            assert profile_mount in volumes
            assert not any("/etc/data/codex" in volume for volume in volumes)
            assert "CODEX_HOME=/etc/data/codex" not in environment


def test_allan_hook_uses_non_dereferencing_ownership_updates() -> None:
    """A path swapped for a symlink cannot redirect the ownership operation."""
    hook = ALLAN_HOOK.read_text(encoding="utf-8")

    assert "! -type l" in hook
    assert "-exec chown -h hermes:hermes {} +" in hook
    assert "chown -R" not in hook
