import subprocess
from pathlib import Path

from gateway import marketplace_updater


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
    assert marketplace_updater.marketplace_config(_config(Path("/tmp/marketplace"), interval_seconds=1)) == {
        "repo_dir": "/tmp/marketplace", "remote": "origin", "branch": "main", "interval_seconds": 30,
    }
    assert marketplace_updater.marketplace_config(_config(Path("/tmp/repo"), remote="--upload-pack=bad")) is None
    assert marketplace_updater.marketplace_config(_config(Path("/tmp/repo"), interval_seconds="bad")) is None


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
