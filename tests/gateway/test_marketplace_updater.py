import subprocess
from pathlib import Path

import pytest

from gateway import marketplace_updater
from gateway.marketplace_config import MarketplaceConfig


def _config(repo: Path, **overrides):
    settings = {"enabled": True, "repo_dir": str(repo), "remote": "origin", "branch": "main"}
    settings.update(overrides)
    return {"skills": {"marketplace": settings}}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, text=True, capture_output=True
    ).stdout.strip()


def _repositories(tmp_path: Path):
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    checkout = tmp_path / "checkout"
    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "init", "-b", "main", str(seed))
    _git(seed, "config", "user.name", "Test")
    _git(seed, "config", "user.email", "test@example.com")
    skills = seed / "plugins" / "skills"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("v1", encoding="utf-8")
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "v1")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")
    _git(tmp_path, "clone", "-b", "main", str(remote), str(checkout))
    return seed, checkout, checkout / "plugins" / "skills"


def test_marketplace_config_is_opt_in_and_validates_values():
    assert marketplace_updater.marketplace_config({"skills": {}}) is None
    assert marketplace_updater.marketplace_config({"skills": {"marketplace": {"enabled": True}}}) is None
    assert marketplace_updater.marketplace_config(
        _config(Path("/tmp/marketplace"), interval_seconds=1)
    ) == MarketplaceConfig(
        repository="",
        repo_dir=Path("/tmp/marketplace"),
        skills_path=Path("plugins/skills"),
        remote="origin",
        branch="main",
        interval_seconds=30,
    )
    assert marketplace_updater.marketplace_config(_config(Path("/tmp/repo"), remote="--upload-pack=bad")) is None
    assert marketplace_updater.marketplace_config(_config(Path("/tmp/repo"), interval_seconds="bad")) is None


@pytest.mark.asyncio
async def test_gateway_watcher_reads_marketplace_from_full_user_config(monkeypatch, tmp_path: Path):
    from gateway import run as gateway_run
    from gateway.config import GatewayConfig
    from hermes_cli import config as user_config

    full_config = _config(tmp_path / "marketplace")
    received = []
    runner = gateway_run.GatewayRunner.__new__(gateway_run.GatewayRunner)
    runner.config = GatewayConfig()
    runner._running = True

    monkeypatch.setattr(user_config, "load_config_readonly", lambda: full_config)

    def update(config):
        received.append(config)
        runner._running = False
        return False

    async def skip_sleep(_interval):
        return None

    monkeypatch.setattr(gateway_run.asyncio, "sleep", skip_sleep)
    monkeypatch.setattr(marketplace_updater, "update_marketplace_worktree", update)

    await runner._marketplace_skills_watcher()

    assert received == [full_config]


def test_update_refuses_checkout_outside_external_skill_roots(monkeypatch, tmp_path: Path):
    repo = tmp_path / "marketplace"
    repo.mkdir()
    monkeypatch.setattr("agent.skill_utils.get_external_skills_dirs", lambda: [tmp_path / "elsewhere"])
    assert not marketplace_updater.update_marketplace_worktree(_config(repo))


def test_update_fast_forwards_and_unchanged_is_noop(monkeypatch, tmp_path: Path):
    seed, checkout, skills = _repositories(tmp_path)
    monkeypatch.setattr("agent.skill_utils.get_external_skills_dirs", lambda: [skills])
    monkeypatch.setattr(marketplace_updater, "_fetch", lambda repo, remote, branch: _git(repo, "fetch", remote, branch))
    (seed / "plugins" / "skills" / "SKILL.md").write_text("v2", encoding="utf-8")
    _git(seed, "commit", "-am", "v2")
    _git(seed, "push")
    assert marketplace_updater.update_marketplace_worktree(_config(checkout))
    assert (skills / "SKILL.md").read_text(encoding="utf-8") == "v2"
    assert not marketplace_updater.update_marketplace_worktree(_config(checkout))


def test_update_refuses_dirty_checkout(monkeypatch, tmp_path: Path):
    _, checkout, skills = _repositories(tmp_path)
    monkeypatch.setattr("agent.skill_utils.get_external_skills_dirs", lambda: [skills])
    (skills / "SKILL.md").write_text("dirty", encoding="utf-8")
    monkeypatch.setattr(marketplace_updater, "_fetch", lambda *args: (_ for _ in ()).throw(AssertionError("fetch called")))
    assert not marketplace_updater.update_marketplace_worktree(_config(checkout))
    assert (skills / "SKILL.md").read_text(encoding="utf-8") == "dirty"


def test_update_refuses_diverged_checkout(monkeypatch, tmp_path: Path):
    seed, checkout, skills = _repositories(tmp_path)
    monkeypatch.setattr("agent.skill_utils.get_external_skills_dirs", lambda: [skills])
    _git(checkout, "config", "user.name", "Test")
    _git(checkout, "config", "user.email", "test@example.com")
    (skills / "local.txt").write_text("local", encoding="utf-8")
    _git(checkout, "add", ".")
    _git(checkout, "commit", "-m", "local")
    (seed / "plugins" / "skills" / "remote.txt").write_text("remote", encoding="utf-8")
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "remote")
    _git(seed, "push")
    monkeypatch.setattr(marketplace_updater, "_fetch", lambda repo, remote, branch: _git(repo, "fetch", remote, branch))
    before = _git(checkout, "rev-parse", "HEAD")
    assert not marketplace_updater.update_marketplace_worktree(_config(checkout))
    assert _git(checkout, "rev-parse", "HEAD") == before


def test_missing_token_and_fetch_failure_fail_closed(monkeypatch, tmp_path: Path):
    _, checkout, skills = _repositories(tmp_path)
    monkeypatch.setattr("agent.skill_utils.get_external_skills_dirs", lambda: [skills])
    monkeypatch.delenv("MARKETPLACE_GIT_AUTH_TOKEN", raising=False)
    assert not marketplace_updater.update_marketplace_worktree(_config(checkout))
    monkeypatch.setattr(marketplace_updater, "_fetch", lambda *args: (_ for _ in ()).throw(subprocess.TimeoutExpired("git", 30)))
    assert not marketplace_updater.update_marketplace_worktree(_config(checkout))


def test_fetch_reads_token_from_vault_env_file_on_each_call(monkeypatch, tmp_path: Path):
    """Gateway fetches use the rendered Vault file, not an inherited secret environment."""
    vault = tmp_path / "vault.env"
    vault.write_text("# rendered by Vault\nMARKETPLACE_GIT_AUTH_TOKEN=\"first-token\"\n", encoding="utf-8")
    monkeypatch.setenv("MARKETPLACE_VAULT_ENV_FILE", str(vault))
    monkeypatch.setenv("MARKETPLACE_GIT_AUTH_TOKEN", "stale-inherited-token")
    seen_tokens = []

    def fake_run(args, **kwargs):
        seen_tokens.append(kwargs["env"]["MARKETPLACE_GIT_AUTH_TOKEN"])
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(marketplace_updater.subprocess, "run", fake_run)
    marketplace_updater._fetch(tmp_path, "origin", "main")
    vault.write_text("MARKETPLACE_GIT_AUTH_TOKEN=\"second-token\"\n", encoding="utf-8")
    marketplace_updater._fetch(tmp_path, "origin", "main")

    assert seen_tokens == ["first-token", "second-token"]


@pytest.mark.parametrize(
    "vault_contents",
    [
        "MARKETPLACE_GIT_AUTH_TOKEN=$(touch should-not-run)\n",
        "export MARKETPLACE_GIT_AUTH_TOKEN=token\n",
        "MARKETPLACE_GIT_AUTH_TOKEN='quoted-token'\n",
    ],
)
def test_fetch_rejects_vault_values_that_require_shell_evaluation(monkeypatch, tmp_path: Path, vault_contents: str):
    vault = tmp_path / "vault.env"
    vault.write_text(vault_contents, encoding="utf-8")
    monkeypatch.setenv("MARKETPLACE_VAULT_ENV_FILE", str(vault))
    monkeypatch.delenv("MARKETPLACE_GIT_AUTH_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="MARKETPLACE_GIT_AUTH_TOKEN"):
        marketplace_updater._fetch(tmp_path, "origin", "main")
