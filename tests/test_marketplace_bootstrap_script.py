"""Focused real-filesystem tests for image-owned marketplace bootstrap."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "docker" / "marketplace-bootstrap.sh"
HOOK = REPO_ROOT / "docker" / "cont-init.d" / "017-marketplace-bootstrap"
DOCKERFILE = REPO_ROOT / "Dockerfile"


def _run_script(
    tmp_path: Path,
    *,
    enabled: str = "true",
    soul: bytes = b"Marketplace soul\n",
    skills_path: str = "skills",
    soul_mode: str = "regular",
    mount_mode: str = "directory",
    marketplace_overrides: dict[str, object] | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the real script against real temporary directories and a fake git binary."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_git = bin_dir / "git"
    fake_git.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "printf '%s\\n' \"$*\" >> \"$GIT_LOG\"\n"
        "for arg in \"$@\"; do\n"
        "  case \"$arg\" in *--file=*) credentials=${arg##*--file=} ;; esac\n"
        "done\n"
        "if [ -n \"${credentials:-}\" ]; then\n"
        "  stat -c '%a' \"$credentials\" > \"$CREDENTIAL_MODE\"\n"
        "  test -s \"$credentials\"\n"
        "  cat \"$credentials\" > \"$CREDENTIAL_CONTENT\"\n"
        "  printf '%s' \"$credentials\" > \"$CREDENTIAL_PATH\"\n"
        "fi\n"
        "for last; do :; done\n"
        "mkdir -p \"$last/$FAKE_SKILLS_PATH\"\n"
        "case \"$FAKE_SOUL_MODE\" in\n"
        "  regular) printf '%s' \"$FAKE_SOUL\" > \"$last/SOUL.md\" ;;\n"
        "  symlink) printf '%s' outside > \"$FAKE_OUTSIDE\"; ln -s \"$FAKE_OUTSIDE\" \"$last/SOUL.md\" ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)

    vault = tmp_path / "vault.env"
    vault.write_text("MARKETPLACE_GIT_AUTH_TOKEN=\"super-secret-token\"\n", encoding="utf-8")
    home = tmp_path / "hermes-home"
    home.mkdir()
    mount = home / "marketplace"
    if mount_mode == "directory":
        mount.mkdir()
    elif mount_mode == "symlink":
        outside_mount = tmp_path / "outside-marketplace"
        outside_mount.mkdir()
        (outside_mount / "sentinel").write_text("preserve", encoding="utf-8")
        mount.symlink_to(outside_mount, target_is_directory=True)
    else:
        raise ValueError(f"unsupported mount mode: {mount_mode}")
    (home / "SOUL.md").write_text("old soul\n", encoding="utf-8")
    marketplace = {
        "enabled": enabled == "true",
        "repository": "https://example.test/private/marketplace.git",
        "repo_dir": str(mount / "repository"),
        "skills_path": skills_path,
        "branch": "main",
    }
    if marketplace_overrides:
        marketplace.update(marketplace_overrides)
    (home / "config.yaml").write_text(
        yaml.safe_dump({"skills": {"marketplace": marketplace}}), encoding="utf-8"
    )
    env = os.environ | {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "MARKETPLACE_VAULT_ENV_FILE": str(vault),
        "HERMES_HOME": str(home),
        "GIT_LOG": str(tmp_path / "git.log"),
        "CREDENTIAL_MODE": str(tmp_path / "credential-mode"),
        "CREDENTIAL_CONTENT": str(tmp_path / "credential-content"),
        "CREDENTIAL_PATH": str(tmp_path / "credential-path"),
        "FAKE_SKILLS_PATH": skills_path,
        "FAKE_SOUL": soul.decode("utf-8"),
        "FAKE_SOUL_MODE": soul_mode,
        "FAKE_OUTSIDE": str(tmp_path / "outside-soul"),
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(["sh", str(SCRIPT)], text=True, capture_output=True, env=env, timeout=15)


def test_bootstrap_is_disabled_unless_enabled_is_literal_true(tmp_path: Path) -> None:
    """Bootstrap must not source secrets or invoke git unless explicitly enabled."""
    result = _run_script(tmp_path, enabled="false")

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "git.log").exists()
    assert (tmp_path / "hermes-home" / "SOUL.md").read_text(encoding="utf-8") == "old soul\n"


def test_bootstrap_clones_validates_and_atomically_installs_soul(tmp_path: Path) -> None:
    """Enabled bootstrap uses shallow single-branch clone and installs validated root SOUL."""
    result = _run_script(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "super-secret-token" not in result.stdout + result.stderr
    git_args = (tmp_path / "git.log").read_text(encoding="utf-8")
    assert "clone --depth 1 --single-branch --no-tags --branch main" in git_args
    assert str(tmp_path / "hermes-home" / "marketplace" / "repository") in git_args
    assert (tmp_path / "credential-mode").read_text(encoding="utf-8").strip() == "600"
    assert (tmp_path / "credential-content").read_text(encoding="utf-8") == (
        "https://x-access-token:super-secret-token@example.test/private/marketplace.git\n"
    )
    credential_path = Path((tmp_path / "credential-path").read_text(encoding="utf-8"))
    assert not credential_path.exists(), "temporary Git credential store was not removed"
    assert (tmp_path / "hermes-home" / "SOUL.md").read_text(encoding="utf-8") == "Marketplace soul\n"


def test_bootstrap_uses_marketplace_config_instead_of_behavior_environment(tmp_path: Path) -> None:
    """Nonsecret bootstrap settings come only from config.yaml, never raw environment."""
    result = _run_script(
        tmp_path,
        extra_env={
            "MARKETPLACE_BOOTSTRAP_ENABLED": "false",
            "MARKETPLACE_REPOSITORY": "https://invalid.test/ignored.git",
            "MARKETPLACE_REF": "ignored",
            "MARKETPLACE_MOUNT_PATH": str(tmp_path / "outside"),
            "MARKETPLACE_SKILLS_PATH": "ignored",
        },
    )

    assert result.returncode == 0, result.stderr
    git_args = (tmp_path / "git.log").read_text(encoding="utf-8")
    assert "https://example.test/private/marketplace.git" in git_args
    assert "--branch main" in git_args
    assert "invalid.test" not in git_args
    assert "ignored" not in git_args


def test_bootstrap_rejects_invalid_root_soul_without_replacing_existing_identity(tmp_path: Path) -> None:
    """Symlinked and oversized root SOUL files never replace the existing identity."""
    for name, kwargs in {
        "symlink": {"soul_mode": "symlink"},
        "oversized": {"soul": b"x" * 20001},
    }.items():
        case = tmp_path / name
        result = _run_script(case, **kwargs)

        assert result.returncode != 0
        assert "super-secret-token" not in result.stdout + result.stderr
        assert (case / "hermes-home" / "SOUL.md").read_text(encoding="utf-8") == "old soul\n"



def test_bootstrap_rejects_marketplace_mount_escapes(tmp_path: Path) -> None:
    """Traversal and symlink escapes must not permit deletion outside HERMES_HOME."""
    traversal_case = tmp_path / "traversal"
    traversal_outside = traversal_case / "outside-marketplace"
    traversal_outside.mkdir(parents=True)
    traversal_sentinel = traversal_outside / "sentinel"
    traversal_sentinel.write_text("preserve", encoding="utf-8")
    traversal_result = _run_script(
        traversal_case,
        marketplace_overrides={
            "repo_dir": str(
                traversal_case / "hermes-home" / "marketplace" / ".." / ".." / "outside-marketplace" / "repository"
            )
        },
    )

    symlink_case = tmp_path / "symlink"
    symlink_result = _run_script(symlink_case, mount_mode="symlink")

    for case, result, sentinel in [
        (traversal_case, traversal_result, traversal_sentinel),
        (symlink_case, symlink_result, symlink_case / "outside-marketplace" / "sentinel"),
    ]:
        assert result.returncode != 0
        assert not (case / "git.log").exists()
        assert sentinel.read_text(encoding="utf-8") == "preserve"
        assert (case / "hermes-home" / "SOUL.md").read_text(encoding="utf-8") == "old soul\n"


def test_image_wires_hermes_hook_in_required_cont_init_order() -> None:
    """The image owns a hermes-user hook positioned after 015 and before 02."""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    hook = HOOK.read_text(encoding="utf-8")

    assert "COPY --chmod=0755 docker/marketplace-bootstrap.sh /opt/hermes/docker/marketplace-bootstrap.sh" in dockerfile
    assert "COPY --chmod=0755 docker/cont-init.d/017-marketplace-bootstrap /etc/cont-init.d/017-marketplace-bootstrap" in dockerfile
    assert "s6-setuidgid hermes /opt/hermes/docker/marketplace-bootstrap.sh" in hook
    assert dockerfile.index("COPY --chmod=0755 docker/cont-init.d/015-supervise-perms") < dockerfile.index("COPY --chmod=0755 docker/cont-init.d/017-marketplace-bootstrap") < dockerfile.index("COPY --chmod=0755 docker/cont-init.d/02-reconcile-profiles")
