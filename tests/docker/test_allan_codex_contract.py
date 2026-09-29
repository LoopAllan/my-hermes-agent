"""Docker lifecycle contract for Allan's derived Codex runtime image."""

from __future__ import annotations

import subprocess

import pytest

from tests.docker.conftest import docker_exec_sh, restart_container, start_container


@pytest.fixture(scope="session")
def allan_image(built_image: str) -> str:
    """Build the actual derived image atop the core image built by the suite."""
    image = "hermes-agent-allan-harness:latest"
    result = subprocess.run(
        [
            "docker", "build", "-f", "Dockerfile.allan", "-t", image,
            "--build-arg", f"BASE_IMAGE={built_image}", ".",
        ],
        capture_output=True, text=True, timeout=1200,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return image


def test_allan_derived_image_preserves_immutable_codex_rules(
    allan_image: str, container_name: str,
) -> None:
    """Derived startup owns mutable Codex state without mutating AGENTS.md."""
    start_container(allan_image, container_name)
    initial = docker_exec_sh(
        container_name,
        "stat -c '%U:%G %a' /etc/data/codex /etc/data/codex/AGENTS.md",
        user="root",
    )
    assert initial.stdout.splitlines() == ["root:hermes 1770", "root:root 444"]

    docker_exec_sh(
        container_name,
        "mkdir -p /etc/data/codex/nested /tmp/codex-link-target && "
        "touch /etc/data/codex/auth.json /etc/data/codex/nested/state "
        "/tmp/codex-link-target/state && "
        "ln -s /tmp/codex-link-target/state /etc/data/codex/link && "
        "chown -R root:root /etc/data/codex/auth.json "
        "/etc/data/codex/nested /tmp/codex-link-target",
        user="root",
    )
    restart_container(container_name)

    repaired = docker_exec_sh(
        container_name,
        "stat -c '%U:%G %a' /etc/data/codex/auth.json "
        "/etc/data/codex/nested/state /etc/data/codex/link "
        "/etc/data/codex/AGENTS.md && "
        "stat -Lc '%U:%G %a' /etc/data/codex/link",
        user="root",
    )
    assert repaired.stdout.splitlines() == [
        "hermes:hermes 644",
        "root:root 644",
        "root:root 777",
        "root:root 444",
        "root:root 644",
    ]
