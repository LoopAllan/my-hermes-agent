from pathlib import Path

from gateway import marketplace_updater


def test_marketplace_config_is_opt_in_and_clamps_interval():
    assert marketplace_updater.marketplace_config({"skills": {}}) is None
    assert marketplace_updater.marketplace_config({"skills": {"marketplace": {"enabled": True}}}) is None
    assert marketplace_updater.marketplace_config({"skills": {"marketplace": {
        "enabled": True, "repo_dir": "/tmp/marketplace", "interval_seconds": 1,
    }}}) == {
        "repo_dir": "/tmp/marketplace", "remote": "origin", "branch": "main", "interval_seconds": 30,
    }


def test_update_refuses_checkout_outside_external_skill_roots(monkeypatch, tmp_path: Path):
    repo = tmp_path / "marketplace"
    repo.mkdir()
    monkeypatch.setattr("agent.skill_utils.get_external_skills_dirs", lambda: [tmp_path / "elsewhere"])
    assert not marketplace_updater.update_marketplace_worktree({"skills": {"marketplace": {
        "enabled": True, "repo_dir": str(repo),
    }}})
