"""Environment contracts for the dashboard compute-host supervisor."""

from __future__ import annotations

import io

from tui_gateway import host_supervisor


class _NoopThread:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def start(self) -> None:
        pass


class _Process:
    pid = 12345
    stdin = io.StringIO()
    stdout = io.StringIO()
    stderr = io.StringIO()

    def poll(self):
        return None


def test_compute_host_final_spawn_env_keeps_only_sanitized_credentials(monkeypatch, tmp_path):
    """The final Popen environment must not reintroduce the raw parent env."""
    captured = {}
    proc = _Process()

    monkeypatch.setenv("GH_TOKEN", "alternate-github-token")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "github-app-key")
    monkeypatch.setenv("HERMES_API_KEY", "gateway-key")
    monkeypatch.setenv("OPENAI_API_KEY", "provider-key")
    monkeypatch.setattr(
        host_supervisor,
        "hermes_subprocess_env",
        lambda *, inherit_credentials: {
            "PATH": "/usr/bin",
            "GITHUB_TOKEN": "agent-token",
        },
    )
    monkeypatch.setattr(host_supervisor, "_Thread", _NoopThread)
    def spawn(*_args, **kwargs):
        captured["env"] = kwargs["env"]
        return proc

    monkeypatch.setattr(host_supervisor.subprocess, "Popen", spawn)

    supervisor = host_supervisor.HostSupervisor(
        autostart=False,
        registry_path=tmp_path / "compute-host.json",
    )
    monkeypatch.setattr(supervisor._hello_event, "wait", lambda timeout: True)
    monkeypatch.setattr(supervisor, "_validate_hello", lambda: None)
    monkeypatch.setattr(supervisor, "_persist_registry", lambda: None)

    supervisor._spawn_locked(reason="test")

    env = captured["env"]
    assert env["GITHUB_TOKEN"] == "agent-token"
    assert "GH_TOKEN" not in env
    assert "GITHUB_APP_PRIVATE_KEY" not in env
    assert "HERMES_API_KEY" not in env
    assert "OPENAI_API_KEY" not in env
