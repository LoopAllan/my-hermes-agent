"""Profile-scope contracts for agent-owned child-process credentials."""

from __future__ import annotations

import pytest

from agent import secret_scope
from tools.code_execution_tool import _scrub_child_env
from tools.environments.local import _make_run_env, hermes_subprocess_env


@pytest.fixture(autouse=True)
def _reset_secret_scope():
    secret_scope.set_multiplex_active(False)
    token = secret_scope.set_secret_scope(None)
    try:
        yield
    finally:
        secret_scope.reset_secret_scope(token)
        secret_scope.set_multiplex_active(False)


@pytest.mark.parametrize(
    "builder",
    [
        lambda: hermes_subprocess_env(),
        lambda: _make_run_env({}),
        lambda: _scrub_child_env({"GITHUB_TOKEN": "process-token"}),
    ],
    ids=["non_terminal", "terminal", "execute_code"],
)
def test_agent_github_token_uses_active_profile_scope(monkeypatch, builder):
    """A multiplexed profile never inherits another profile's process token."""
    monkeypatch.setenv("GITHUB_TOKEN", "process-token")
    secret_scope.set_multiplex_active(True)
    token = secret_scope.set_secret_scope({"GITHUB_TOKEN": "profile-b-token"})
    try:
        assert builder().get("GITHUB_TOKEN") == "profile-b-token"
    finally:
        secret_scope.reset_secret_scope(token)


@pytest.mark.parametrize(
    "builder",
    [
        lambda: hermes_subprocess_env(),
        lambda: _make_run_env({}),
        lambda: _scrub_child_env({"GITHUB_TOKEN": "process-token"}),
    ],
    ids=["non_terminal", "terminal", "execute_code"],
)
def test_agent_github_token_is_absent_when_active_profile_scope_omits_it(monkeypatch, builder):
    """An empty multiplex scope fails closed instead of borrowing process env."""
    monkeypatch.setenv("GITHUB_TOKEN", "process-token")
    secret_scope.set_multiplex_active(True)
    token = secret_scope.set_secret_scope({})
    try:
        assert "GITHUB_TOKEN" not in builder()
    finally:
        secret_scope.reset_secret_scope(token)
