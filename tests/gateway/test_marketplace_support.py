"""Contracts shared by marketplace bootstrap and gateway updates."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
import hermes_yaml as yaml

import gateway.marketplace_bootstrap as marketplace_bootstrap
from gateway.marketplace_config import (
    MarketplaceConfig,
    MarketplaceConfigError,
    load_marketplace_config,
    load_marketplace_config_file,
)
from gateway.marketplace_credentials import GitAuthEnvironment, read_marketplace_token


def _settings(repo: Path, **overrides: object) -> dict[str, object]:
    settings: dict[str, object] = {
        "enabled": True,
        "repository": "https://example.test/private/marketplace.git",
        "repo_dir": str(repo),
        "skills_path": "plugins/skills",
        "remote": "origin",
        "branch": "main",
        "interval_seconds": 10,
    }
    settings.update(overrides)
    return {"skills": {"marketplace": settings}}


def test_config_loader_returns_value_object_and_applies_shared_defaults(tmp_path: Path) -> None:
    config = load_marketplace_config(_settings(tmp_path / "repo"), require_bootstrap=True)

    assert config == MarketplaceConfig(
        repository="https://example.test/private/marketplace.git",
        repo_dir=tmp_path / "repo",
        skills_path=Path("plugins/skills"),
        remote="origin",
        branch="main",
        interval_seconds=30,
    )


def test_config_loader_disabled_is_noop_without_validating_unused_values() -> None:
    assert load_marketplace_config({"skills": {"marketplace": {"enabled": False}}}) is None
    assert load_marketplace_config({"skills": {}}) is None


def test_config_loader_rejects_invalid_enabled_configuration(tmp_path: Path) -> None:
    with pytest.raises(MarketplaceConfigError, match="mapping"):
        load_marketplace_config({"skills": {"marketplace": "enabled"}})
    with pytest.raises(MarketplaceConfigError, match="remote and branch"):
        load_marketplace_config(_settings(tmp_path / "repo", remote="--upload-pack=bad"))
    with pytest.raises(MarketplaceConfigError, match="remote"):
        load_marketplace_config(_settings(tmp_path / "repo", remote="   "))
    with pytest.raises(MarketplaceConfigError, match="repo_dir"):
        load_marketplace_config(_settings(tmp_path / "repo", repo_dir="   "))
    with pytest.raises(MarketplaceConfigError, match="interval_seconds"):
        load_marketplace_config(_settings(tmp_path / "repo", interval_seconds="bad"))
    with pytest.raises(MarketplaceConfigError, match="repository"):
        load_marketplace_config(
            _settings(tmp_path / "repo", repository=""), require_bootstrap=True
        )


def test_file_loader_reads_only_config_yaml_marketplace_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    expected = _settings(tmp_path / "repo")
    (home / "config.yaml").write_text(yaml.safe_dump(expected), encoding="utf-8")
    monkeypatch.setenv("MARKETPLACE_REPOSITORY", "https://ignored.test/repo.git")

    assert load_marketplace_config_file(home, require_bootstrap=True) == load_marketplace_config(
        expected, require_bootstrap=True
    )


@pytest.mark.parametrize(
    ("rendered", "expected"),
    [
        ('MARKETPLACE_GIT_AUTH_TOKEN="double quoted"\n', "double quoted"),
        ('MARKETPLACE_GIT_AUTH_TOKEN="quote\\\"slash\\\\token"\n', 'quote"slash\\token'),
        (r"MARKETPLACE_GIT_AUTH_TOKEN=percent\ q\ token" + "\n", "percent q token"),
        (r"MARKETPLACE_GIT_AUTH_TOKEN=special\$token" + "\n", "special$token"),
    ],
)
def test_token_parser_accepts_safe_printf_percent_q_words(
    tmp_path: Path, rendered: str, expected: str
) -> None:
    vault = tmp_path / "vault.env"
    vault.write_text(rendered, encoding="utf-8")

    assert read_marketplace_token(vault) == expected


@pytest.mark.parametrize(
    "rendered",
    [
        "MARKETPLACE_GIT_AUTH_TOKEN=$(id)\n",
        "MARKETPLACE_GIT_AUTH_TOKEN=`id`\n",
        "MARKETPLACE_GIT_AUTH_TOKEN='single-quoted'\n",
        "export MARKETPLACE_GIT_AUTH_TOKEN=token\n",
        "MARKETPLACE_GIT_AUTH_TOKEN=\n",
    ],
)
def test_token_parser_rejects_non_percent_q_or_shell_evaluated_values(
    tmp_path: Path, rendered: str
) -> None:
    vault = tmp_path / "vault.env"
    vault.write_text(rendered, encoding="utf-8")

    with pytest.raises(RuntimeError, match="MARKETPLACE_GIT_AUTH_TOKEN"):
        read_marketplace_token(vault)


def test_token_parser_rejects_go_escaped_newline_after_decoding(tmp_path: Path) -> None:
    """A Vault printf %q value must be screened after Go escape decoding."""
    vault = tmp_path / "vault.env"
    vault.write_text('MARKETPLACE_GIT_AUTH_TOKEN="line\\nbreak"\n', encoding="utf-8")

    with pytest.raises(RuntimeError, match="MARKETPLACE_GIT_AUTH_TOKEN"):
        read_marketplace_token(vault)


def test_token_parser_accepts_bom_prefixed_vault_env_file(tmp_path: Path) -> None:
    vault = tmp_path / "vault.env"
    vault.write_text('MARKETPLACE_GIT_AUTH_TOKEN="bom-safe"\n', encoding="utf-8-sig")

    assert read_marketplace_token(vault) == "bom-safe"


def _treat_existing_checkout_as_replaceable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap-mechanics tests seed a plain directory; preservation has its own tests below."""
    monkeypatch.setattr(marketplace_bootstrap.MarketplaceBootstrap, "_local_state", classmethod(lambda *a: ""))


# The bootstrap anchors clone paths at /proc/self/fd, which only Linux (the container) provides.
@pytest.mark.platforms("linux")
def test_bootstrap_parent_symlink_swap_cannot_redirect_clone_or_deletion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An opened parent fd keeps cleanup and clone out of a later symlink target."""
    _treat_existing_checkout_as_replaceable(monkeypatch)
    home = tmp_path / "home"
    parent = home / "marketplace"
    repository = parent / "repository"
    outside = tmp_path / "outside"
    home.mkdir()
    repository.mkdir(parents=True)
    (repository / "old").write_text("replace me", encoding="utf-8")
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("preserve", encoding="utf-8")

    config = load_marketplace_config(_settings(repository), require_bootstrap=True)
    assert config is not None
    original_rmtree: Any = marketplace_bootstrap.shutil.rmtree
    swapped = False

    def swap_parent_then_remove(
        path: str | Path,
        ignore_errors: bool = False,
        *,
        dir_fd: int | None = None,
        onerror: Any = None,
    ) -> None:
        nonlocal swapped
        if not swapped:
            moved_parent = home / "marketplace-before-swap"
            parent.rename(moved_parent)
            parent.symlink_to(outside, target_is_directory=True)
            swapped = True
        original_rmtree(path, ignore_errors, onerror, dir_fd=dir_fd)

    class FakeGitAuth:
        def __enter__(self) -> dict[str, str]:
            return os.environ.copy()

        def __exit__(self, *args: object) -> None:
            return None

    clone_targets: list[Path] = []

    def fake_git(args: list[str], **kwargs: object) -> None:
        target = Path(args[-1])
        clone_targets.append(target.resolve())
        (target / "plugins" / "skills").mkdir(parents=True)
        (target / "SOUL.md").write_text("new soul", encoding="utf-8")

    monkeypatch.setattr(marketplace_bootstrap.shutil, "rmtree", swap_parent_then_remove)
    monkeypatch.setattr(marketplace_bootstrap.GitAuthEnvironment, "from_vault", lambda: FakeGitAuth())
    monkeypatch.setattr(marketplace_bootstrap.subprocess, "run", fake_git)

    marketplace_bootstrap.MarketplaceBootstrap(home, config).run()

    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert not (outside / "repository").exists()
    assert clone_targets and outside not in clone_targets[0].parents
    assert (home / "SOUL.md").read_text(encoding="utf-8") == "new soul"


def test_bootstrap_refuses_final_repository_symlink_without_touching_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A final symlink is not unlinked or followed during bootstrap cleanup."""
    home = tmp_path / "home"
    parent = home / "marketplace"
    repository = parent / "repository"
    home.mkdir()
    parent.mkdir()
    outside = home / "other-in-home-directory"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("preserve", encoding="utf-8")
    repository.symlink_to(outside, target_is_directory=True)
    config = load_marketplace_config(_settings(repository), require_bootstrap=True)
    assert config is not None

    with pytest.raises(RuntimeError, match="repository directory"):
        marketplace_bootstrap.MarketplaceBootstrap(home, config).run()

    assert repository.is_symlink()
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_git_auth_environment_refreshes_vault_token_and_cleans_helper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    vault = tmp_path / "vault.env"
    vault.write_text('MARKETPLACE_GIT_AUTH_TOKEN="first"\n', encoding="utf-8")
    monkeypatch.setenv("MARKETPLACE_VAULT_ENV_FILE", str(vault))
    monkeypatch.setenv("MARKETPLACE_GIT_AUTH_TOKEN", "stale")

    with GitAuthEnvironment.from_vault() as first:
        first_helper = Path(first["GIT_ASKPASS"])
        assert first["MARKETPLACE_GIT_AUTH_TOKEN"] == "first"
        assert first["GIT_TERMINAL_PROMPT"] == "0"
        assert first_helper.stat().st_mode & 0o777 == 0o700
        assert "first" not in first_helper.read_text(encoding="utf-8")
        assert os.environ["MARKETPLACE_GIT_AUTH_TOKEN"] == "stale"
    assert not first_helper.exists()

    vault.write_text('MARKETPLACE_GIT_AUTH_TOKEN="second"\n', encoding="utf-8")
    with GitAuthEnvironment.from_vault() as second:
        assert second["MARKETPLACE_GIT_AUTH_TOKEN"] == "second"


def test_marketplace_git_children_never_inherit_launch_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Git runs for whichever profile owns the marketplace; the launch process's secrets stay behind."""
    from gateway import marketplace_updater

    vault = tmp_path / "vault.env"
    vault.write_text('MARKETPLACE_GIT_AUTH_TOKEN="scoped"\n', encoding="utf-8")
    monkeypatch.setenv("MARKETPLACE_VAULT_ENV_FILE", str(vault))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-launch-profile")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "launch-bot")
    monkeypatch.setenv("GITHUB_TOKEN", "launch-github")

    with GitAuthEnvironment.from_vault() as authenticated:
        assert authenticated["MARKETPLACE_GIT_AUTH_TOKEN"] == "scoped"
        assert authenticated["GIT_TERMINAL_PROMPT"] == "0"
        for env in (authenticated, marketplace_updater._git_env()):
            assert not {"OPENAI_API_KEY", "TELEGRAM_BOT_TOKEN", "GITHUB_TOKEN"} & set(env)
    assert "MARKETPLACE_GIT_AUTH_TOKEN" not in marketplace_updater._git_env()


def test_relative_repo_dir_resolves_under_the_owning_hermes_home(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Bootstrap, updater and discovery must agree on where a relative repo_dir lives."""
    from hermes_constants import get_hermes_home

    home = tmp_path / "profile-home"
    home.mkdir()
    monkeypatch.chdir(tmp_path)  # a cwd-relative resolution would land outside the home
    config = _settings(Path("marketplace/repository"))
    (home / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")

    from_file = load_marketplace_config_file(home, require_bootstrap=True)
    assert from_file is not None and from_file.repo_dir == home / "marketplace" / "repository"
    in_scope = load_marketplace_config(config)
    assert in_scope is not None and in_scope.repo_dir == get_hermes_home() / "marketplace" / "repository"


def test_vault_file_comes_from_the_active_profile_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Under multiplex a secondary profile authenticates with its own Vault file, never the launch one."""
    from agent import secret_scope

    launch_vault, profile_vault = tmp_path / "launch.env", tmp_path / "profile.env"
    launch_vault.write_text('MARKETPLACE_GIT_AUTH_TOKEN="launch"\n', encoding="utf-8")
    profile_vault.write_text('MARKETPLACE_GIT_AUTH_TOKEN="profile"\n', encoding="utf-8")
    monkeypatch.setenv("MARKETPLACE_VAULT_ENV_FILE", str(launch_vault))
    secret_scope.set_multiplex_active(True)
    token = secret_scope.set_secret_scope(
        {"MARKETPLACE_VAULT_ENV_FILE": str(profile_vault)}, profile_home=str(tmp_path / "work")
    )
    try:
        with GitAuthEnvironment.from_vault() as env:
            assert env["MARKETPLACE_GIT_AUTH_TOKEN"] == "profile"
    finally:
        secret_scope.reset_secret_scope(token)
        secret_scope.set_multiplex_active(False)


@pytest.mark.platforms("linux")
def test_failed_clone_keeps_the_existing_checkout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A transient Git failure on restart must not delete the checkout that is still serving skills."""
    _treat_existing_checkout_as_replaceable(monkeypatch)
    import subprocess

    home = tmp_path / "home"
    repository = home / "marketplace" / "repository"
    (repository / "plugins" / "skills").mkdir(parents=True)
    (repository / "plugins" / "skills" / "SKILL.md").write_text("serving", encoding="utf-8")
    config = load_marketplace_config(_settings(repository), require_bootstrap=True)
    assert config is not None

    class FakeGitAuth:
        def __enter__(self) -> dict[str, str]:
            return {}

        def __exit__(self, *args: object) -> None:
            return None

    def failing_clone(args: list[str], **kwargs: object) -> None:
        raise subprocess.CalledProcessError(128, args)

    monkeypatch.setattr(marketplace_bootstrap.GitAuthEnvironment, "from_vault", lambda: FakeGitAuth())
    monkeypatch.setattr(marketplace_bootstrap.subprocess, "run", failing_clone)

    with pytest.raises(subprocess.CalledProcessError):
        marketplace_bootstrap.MarketplaceBootstrap(home, config).run()

    assert (repository / "plugins" / "skills" / "SKILL.md").read_text(encoding="utf-8") == "serving"
    assert [p.name for p in repository.parent.iterdir()] == ["repository"]


@pytest.mark.platforms("linux")
def test_failed_checkout_swap_leaves_the_profile_soul_untouched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """SOUL.md and the skills checkout change together: a failed swap commits neither."""
    _treat_existing_checkout_as_replaceable(monkeypatch)
    home = tmp_path / "home"
    repository = home / "marketplace" / "repository"
    repository.mkdir(parents=True)
    (home / "SOUL.md").write_text("old soul", encoding="utf-8")
    config = load_marketplace_config(_settings(repository), require_bootstrap=True)
    assert config is not None

    class FakeGitAuth:
        def __enter__(self) -> dict[str, str]:
            return {}

        def __exit__(self, *args: object) -> None:
            return None

    def fake_clone(args: list[str], **kwargs: object) -> None:
        target = Path(args[-1])
        (target / "plugins" / "skills").mkdir(parents=True)
        (target / "SOUL.md").write_text("new soul", encoding="utf-8")

    def failing_swap(*args: object) -> None:
        raise OSError("destination raced")

    monkeypatch.setattr(marketplace_bootstrap.GitAuthEnvironment, "from_vault", lambda: FakeGitAuth())
    monkeypatch.setattr(marketplace_bootstrap.subprocess, "run", fake_clone)
    monkeypatch.setattr(marketplace_bootstrap.MarketplaceBootstrap, "_swap_in_clone", staticmethod(failing_swap))

    with pytest.raises(OSError, match="destination raced"):
        marketplace_bootstrap.MarketplaceBootstrap(home, config).run()

    assert (home / "SOUL.md").read_text(encoding="utf-8") == "old soul"
    assert sorted(p.name for p in home.iterdir() if p.name != ".marketplace.lock") == ["SOUL.md", "marketplace"]


@pytest.mark.platforms("linux")
def test_failed_swap_restores_the_retired_checkout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """If installing the new clone fails after the old one was moved aside, the old one comes back."""
    _treat_existing_checkout_as_replaceable(monkeypatch)
    home = tmp_path / "home"
    repository = home / "marketplace" / "repository"
    (repository / "plugins" / "skills").mkdir(parents=True)
    (repository / "plugins" / "skills" / "SKILL.md").write_text("serving", encoding="utf-8")
    config = load_marketplace_config(_settings(repository), require_bootstrap=True)
    assert config is not None

    class FakeGitAuth:
        def __enter__(self) -> dict[str, str]:
            return {}

        def __exit__(self, *args: object) -> None:
            return None

    def fake_clone(args: list[str], **kwargs: object) -> None:
        target = Path(args[-1])
        (target / "plugins" / "skills").mkdir(parents=True)
        (target / "SOUL.md").write_text("new soul", encoding="utf-8")

    real_replace = marketplace_bootstrap.os.replace

    def failing_install(src: str, dst: str, **kwargs: object) -> None:
        if ".marketplace-clone-" in str(src):
            raise OSError("destination raced")
        real_replace(src, dst, **kwargs)

    monkeypatch.setattr(marketplace_bootstrap.GitAuthEnvironment, "from_vault", lambda: FakeGitAuth())
    monkeypatch.setattr(marketplace_bootstrap.subprocess, "run", fake_clone)
    monkeypatch.setattr(marketplace_bootstrap.os, "replace", failing_install)

    with pytest.raises(OSError, match="destination raced"):
        marketplace_bootstrap.MarketplaceBootstrap(home, config).run()

    assert (repository / "plugins" / "skills" / "SKILL.md").read_text(encoding="utf-8") == "serving"
    assert [p.name for p in repository.parent.iterdir()] == ["repository"]


def test_repo_dir_placeholders_resolve_in_the_active_profile_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A secondary profile's ${VAR} never picks up the launch process's value of that variable."""
    from agent import secret_scope

    monkeypatch.setenv("MARKETPLACE_ROOT", str(tmp_path / "launch-checkout"))
    secret_scope.set_multiplex_active(True)
    token = secret_scope.set_secret_scope({}, profile_home=str(tmp_path / "work"))
    try:
        config = load_marketplace_config(
            _settings(Path("${MARKETPLACE_ROOT}/repository")), hermes_home=tmp_path / "work"
        )
    finally:
        secret_scope.reset_secret_scope(token)
        secret_scope.set_multiplex_active(False)

    assert config is not None
    assert "launch-checkout" not in str(config.repo_dir)


@pytest.mark.platforms("linux")
def test_retired_checkout_cleanup_failure_still_publishes_a_consistent_revision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cleanup of the old tree is best-effort and runs after SOUL.md matches the new checkout."""
    _treat_existing_checkout_as_replaceable(monkeypatch)
    home = tmp_path / "home"
    repository = home / "marketplace" / "repository"
    (repository / "plugins" / "skills").mkdir(parents=True)
    (home / "SOUL.md").write_text("old soul", encoding="utf-8")
    config = load_marketplace_config(_settings(repository), require_bootstrap=True)
    assert config is not None

    class FakeGitAuth:
        def __enter__(self) -> dict[str, str]:
            return {}

        def __exit__(self, *args: object) -> None:
            return None

    def fake_clone(args: list[str], **kwargs: object) -> None:
        target = Path(args[-1])
        (target / "plugins" / "skills").mkdir(parents=True)
        (target / "plugins" / "skills" / "SKILL.md").write_text("new", encoding="utf-8")
        (target / "SOUL.md").write_text("new soul", encoding="utf-8")

    def failing_rmtree(path: str, *args: object, **kwargs: object) -> None:
        raise OSError("device busy")

    monkeypatch.setattr(marketplace_bootstrap.GitAuthEnvironment, "from_vault", lambda: FakeGitAuth())
    monkeypatch.setattr(marketplace_bootstrap.subprocess, "run", fake_clone)
    monkeypatch.setattr(marketplace_bootstrap.shutil, "rmtree", failing_rmtree)

    marketplace_bootstrap.MarketplaceBootstrap(home, config).run()

    assert (repository / "plugins" / "skills" / "SKILL.md").read_text(encoding="utf-8") == "new"
    assert (home / "SOUL.md").read_text(encoding="utf-8") == "new soul"
    assert "device busy" in capsys.readouterr().err


@pytest.mark.platforms("linux")
def test_failed_soul_publish_rolls_the_checkout_back(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """If SOUL.md cannot be published, the previous checkout serves again beside the previous SOUL."""
    _treat_existing_checkout_as_replaceable(monkeypatch)
    home = tmp_path / "home"
    repository = home / "marketplace" / "repository"
    (repository / "plugins" / "skills").mkdir(parents=True)
    (repository / "plugins" / "skills" / "SKILL.md").write_text("old", encoding="utf-8")
    (home / "SOUL.md").write_text("old soul", encoding="utf-8")
    config = load_marketplace_config(_settings(repository), require_bootstrap=True)
    assert config is not None

    class FakeGitAuth:
        def __enter__(self) -> dict[str, str]:
            return {}

        def __exit__(self, *args: object) -> None:
            return None

    def fake_clone(args: list[str], **kwargs: object) -> None:
        target = Path(args[-1])
        (target / "plugins" / "skills").mkdir(parents=True)
        (target / "plugins" / "skills" / "SKILL.md").write_text("new", encoding="utf-8")
        (target / "SOUL.md").write_text("new soul", encoding="utf-8")

    real_replace = marketplace_bootstrap.os.replace

    def failing_soul_publish(src: str, dst: str, **kwargs: object) -> None:
        if str(dst).endswith("SOUL.md"):
            raise OSError("SOUL.md is a directory now")
        real_replace(src, dst, **kwargs)

    monkeypatch.setattr(marketplace_bootstrap.GitAuthEnvironment, "from_vault", lambda: FakeGitAuth())
    monkeypatch.setattr(marketplace_bootstrap.subprocess, "run", fake_clone)
    monkeypatch.setattr(marketplace_bootstrap.os, "replace", failing_soul_publish)

    with pytest.raises(OSError, match="SOUL.md is a directory now"):
        marketplace_bootstrap.MarketplaceBootstrap(home, config).run()

    assert (repository / "plugins" / "skills" / "SKILL.md").read_text(encoding="utf-8") == "old"
    assert (home / "SOUL.md").read_text(encoding="utf-8") == "old soul"
    assert [p.name for p in repository.parent.iterdir()] == ["repository"]


@pytest.mark.platforms("linux")
def test_bootstrap_keeps_a_dirty_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Like the updater, a restart never destroys local changes in the served checkout."""
    import subprocess

    home = tmp_path / "home"
    repository = home / "marketplace" / "repository"
    (repository / "plugins" / "skills").mkdir(parents=True)
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(repository), *args], check=True)
    (repository / "plugins" / "skills" / "SKILL.md").write_text("committed", encoding="utf-8")
    subprocess.run(["git", "-C", str(repository), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repository), "commit", "-qm", "seed"], check=True)
    (repository / "plugins" / "skills" / "SKILL.md").write_text("local edit", encoding="utf-8")
    (home / "SOUL.md").write_text("old soul", encoding="utf-8")
    config = load_marketplace_config(_settings(repository), require_bootstrap=True)
    assert config is not None
    real_run = subprocess.run

    def no_clone(args: list[str], **kwargs: object):
        assert "clone" not in args, "a dirty checkout must not be replaced"
        return real_run(args, **kwargs)

    monkeypatch.setattr(marketplace_bootstrap.subprocess, "run", no_clone)

    marketplace_bootstrap.MarketplaceBootstrap(home, config).run()

    assert (repository / "plugins" / "skills" / "SKILL.md").read_text(encoding="utf-8") == "local edit"
    assert (home / "SOUL.md").read_text(encoding="utf-8") == "old soul"
    assert "local changes" in capsys.readouterr().err


def _clone_with_local_commit(tmp_path: Path, repository: Path) -> None:
    import subprocess

    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    run = lambda *args, cwd=None: subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)  # noqa: E731
    run("init", "-q", "--bare", str(remote))
    run("init", "-q", "-b", "main", str(seed))
    (seed / "plugins" / "skills").mkdir(parents=True)
    (seed / "plugins" / "skills" / "SKILL.md").write_text("pushed", encoding="utf-8")
    for args in (["config", "user.email", "t@t"], ["config", "user.name", "t"], ["add", "-A"],
                 ["commit", "-qm", "seed"], ["push", "-q", str(remote), "main"]):
        run(*args, cwd=seed)
    run("clone", "-q", "-b", "main", str(remote), str(repository))
    (repository / "plugins" / "skills" / "SKILL.md").write_text("unpushed", encoding="utf-8")
    for args in (["config", "user.email", "t@t"], ["config", "user.name", "t"], ["commit", "-qam", "local"]):
        run(*args, cwd=repository)


@pytest.mark.platforms("linux")
@pytest.mark.parametrize("state", ["unpushed-commit", "foreign-files"])
def test_bootstrap_keeps_state_it_cannot_recreate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str], state: str
) -> None:
    """A clean checkout with local-only commits, or a non-checkout directory with files, survives restarts."""
    import subprocess

    home = tmp_path / "home"
    repository = home / "marketplace" / "repository"
    if state == "unpushed-commit":
        repository.parent.mkdir(parents=True)
        _clone_with_local_commit(tmp_path, repository)
        sentinel, expected = repository / "plugins" / "skills" / "SKILL.md", "unpushed"
    else:
        repository.mkdir(parents=True)
        sentinel, expected = repository / "notes.txt", "operator data"
        sentinel.write_text(expected, encoding="utf-8")
    config = load_marketplace_config(_settings(repository), require_bootstrap=True)
    assert config is not None
    real_run = subprocess.run

    def no_clone(args: list[str], **kwargs: object):
        assert "clone" not in args, "existing state must not be replaced"
        return real_run(args, **kwargs)

    monkeypatch.setattr(marketplace_bootstrap.subprocess, "run", no_clone)

    marketplace_bootstrap.MarketplaceBootstrap(home, config).run()

    assert sentinel.read_text(encoding="utf-8") == expected
    assert "keeping" in capsys.readouterr().err


@pytest.mark.platforms("linux")
def test_checkout_that_gains_local_state_during_the_clone_is_kept(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Local state is re-checked right before the swap, not only before the (slow) clone."""
    home = tmp_path / "home"
    repository = home / "marketplace" / "repository"
    (repository / "plugins" / "skills").mkdir(parents=True)
    (repository / "plugins" / "skills" / "SKILL.md").write_text("serving", encoding="utf-8")
    (home / "SOUL.md").write_text("old soul", encoding="utf-8")
    config = load_marketplace_config(_settings(repository), require_bootstrap=True)
    assert config is not None
    observations = iter(["", "it has local changes"])
    monkeypatch.setattr(
        marketplace_bootstrap.MarketplaceBootstrap, "_local_state", classmethod(lambda *a: next(observations))
    )

    class FakeGitAuth:
        def __enter__(self) -> dict[str, str]:
            return {}

        def __exit__(self, *args: object) -> None:
            return None

    def fake_clone(args: list[str], **kwargs: object) -> None:
        target = Path(args[-1])
        (target / "plugins" / "skills").mkdir(parents=True)
        (target / "SOUL.md").write_text("new soul", encoding="utf-8")

    monkeypatch.setattr(marketplace_bootstrap.GitAuthEnvironment, "from_vault", lambda: FakeGitAuth())
    monkeypatch.setattr(marketplace_bootstrap.subprocess, "run", fake_clone)

    marketplace_bootstrap.MarketplaceBootstrap(home, config).run()

    assert (repository / "plugins" / "skills" / "SKILL.md").read_text(encoding="utf-8") == "serving"
    assert (home / "SOUL.md").read_text(encoding="utf-8") == "old soul"
    assert [p.name for p in repository.parent.iterdir()] == ["repository"]
    assert "local changes" in capsys.readouterr().err


@pytest.mark.platforms("linux")
def test_bootstrapped_checkout_updates_through_a_custom_remote_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """skills.marketplace.remote names the clone's remote, so the updater can fetch through it."""
    import subprocess

    from gateway import marketplace_updater

    def git(*args: str, cwd: Path | None = None) -> str:
        return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    git("init", "-q", "--bare", str(remote))
    git("init", "-q", "-b", "main", str(seed))
    (seed / "plugins" / "skills").mkdir(parents=True)
    (seed / "plugins" / "skills" / "SKILL.md").write_text("v1", encoding="utf-8")
    (seed / "SOUL.md").write_text("soul", encoding="utf-8")
    for args in (["config", "user.email", "t@t"], ["config", "user.name", "t"], ["add", "-A"],
                 ["commit", "-qm", "v1"], ["push", "-q", str(remote), "main"]):
        git(*args, cwd=seed)
    home = tmp_path / "home"
    repository = home / "marketplace" / "repository"
    repository.parent.mkdir(parents=True)
    settings = _settings(repository, repository=str(remote), remote="market")
    config = load_marketplace_config(settings, require_bootstrap=True)
    assert config is not None

    class PlainGit:
        def __enter__(self) -> dict[str, str]:
            return dict(os.environ, GIT_TERMINAL_PROMPT="0")

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(marketplace_bootstrap.GitAuthEnvironment, "from_vault", lambda: PlainGit())
    marketplace_bootstrap.MarketplaceBootstrap(home, config).run()
    assert git("-C", str(repository), "remote") == "market"

    (seed / "plugins" / "skills" / "SKILL.md").write_text("v2", encoding="utf-8")
    git("commit", "-qam", "v2", cwd=seed)
    git("push", "-q", str(remote), "main", cwd=seed)
    monkeypatch.setattr("agent.skill_utils.get_external_skills_dirs", lambda: [repository / "plugins" / "skills"])
    monkeypatch.setattr(
        marketplace_updater, "_fetch", lambda repo, name, branch: git("-C", str(repo), "fetch", "-q", name, branch)
    )

    assert marketplace_updater.update_marketplace_worktree(settings)
    assert (repository / "plugins" / "skills" / "SKILL.md").read_text(encoding="utf-8") == "v2"


def test_marketplace_mutations_wait_for_the_per_home_lock(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Services sharing one HERMES_HOME serialize bootstrap and updates instead of interleaving them."""
    import threading

    from gateway import marketplace_config, marketplace_updater

    home = tmp_path / "home"
    repository = home / "marketplace" / "repository"
    repository.mkdir(parents=True)
    config = load_marketplace_config(_settings(repository), require_bootstrap=True)
    assert config is not None
    monkeypatch.setattr(marketplace_config, "_LOCK_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(
        marketplace_bootstrap.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran unlocked"))
    )
    held, release = threading.Event(), threading.Event()

    def other_service() -> None:
        with marketplace_config.marketplace_lock(home):
            held.set()
            release.wait(10)

    holder = threading.Thread(target=other_service)
    holder.start()
    held.wait(10)
    try:
        with pytest.raises(TimeoutError):
            marketplace_bootstrap.MarketplaceBootstrap(home, config).run()
        monkeypatch.setattr("hermes_constants.get_hermes_home", lambda: home)
        monkeypatch.setattr(
            "agent.skill_utils.get_external_skills_dirs",
            lambda: (_ for _ in ()).throw(AssertionError("update ran unlocked")),
        )
        assert not marketplace_updater.update_marketplace_worktree(_settings(repository))
    finally:
        release.set()
        holder.join(10)
