"""Authorization contracts for plugin-declared group and room chat allowlists."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platform_registry import PlatformEntry, platform_registry
from gateway.session import SessionSource


def _runner_for(platform: Platform, *, extra: dict | None = None):
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={platform: PlatformConfig(enabled=True, extra=extra or {})}
    )
    runner.adapters = {platform: SimpleNamespace(send=AsyncMock())}
    runner.pairing_store = MagicMock()
    runner.pairing_store.is_approved.return_value = False
    return runner


def _source(platform: Platform, *, chat_type: str, chat_id: str, user_id: str) -> SessionSource:
    return SessionSource(
        platform=platform,
        chat_id=chat_id,
        chat_type=chat_type,
        user_id=user_id,
        user_name="unlisted sender",
    )


def _register_line(monkeypatch) -> Platform:
    line = Platform("line")
    entry = PlatformEntry(
        name="line",
        label="LINE",
        adapter_factory=lambda _config: None,
        check_fn=lambda: True,
        allowed_users_env="LINE_ALLOWED_USERS",
        allowed_group_chats_env="LINE_ALLOWED_GROUPS",
        allowed_room_chats_env="LINE_ALLOWED_ROOMS",
        chat_allowlist_authorization_config_key="authorize_allowed_chats",
    )
    monkeypatch.setitem(platform_registry._entries, "line", entry)
    return line


def test_plugin_group_allowlist_authorizes_unlisted_sender(monkeypatch):
    """A listed LINE group is a chat-level grant, independent of its sender."""
    monkeypatch.setenv("LINE_ALLOWED_USERS", "U-owner")
    monkeypatch.setenv("LINE_ALLOWED_GROUPS", "C-family")
    monkeypatch.delenv("LINE_ALLOWED_ROOMS", raising=False)
    monkeypatch.delenv("GATEWAY_ALLOWED_USERS", raising=False)
    line = _register_line(monkeypatch)

    assert _runner_for(line, extra={"authorize_allowed_chats": True})._is_user_authorized(
        _source(line, chat_type="group", chat_id="C-family", user_id="U-someone-else")
    ) is True


def test_plugin_group_allowlist_requires_explicit_profile_opt_in(monkeypatch):
    """A plugin's chat allowlist cannot widen access until its profile opts in."""
    monkeypatch.setenv("LINE_ALLOWED_USERS", "U-owner")
    monkeypatch.setenv("LINE_ALLOWED_GROUPS", "C-family")
    monkeypatch.delenv("LINE_ALLOWED_ROOMS", raising=False)
    monkeypatch.delenv("GATEWAY_ALLOWED_USERS", raising=False)
    line = _register_line(monkeypatch)

    assert _runner_for(line)._is_user_authorized(
        _source(line, chat_type="group", chat_id="C-family", user_id="U-someone-else")
    ) is False


def test_plugin_group_allowlist_does_not_open_other_groups(monkeypatch):
    """A LINE group grant must not bypass sender controls in other groups."""
    monkeypatch.setenv("LINE_ALLOWED_USERS", "U-owner")
    monkeypatch.setenv("LINE_ALLOWED_GROUPS", "C-family")
    monkeypatch.delenv("LINE_ALLOWED_ROOMS", raising=False)
    monkeypatch.delenv("GATEWAY_ALLOWED_USERS", raising=False)
    line = _register_line(monkeypatch)

    assert _runner_for(line, extra={"authorize_allowed_chats": True})._is_user_authorized(
        _source(line, chat_type="group", chat_id="C-other", user_id="U-someone-else")
    ) is False


def test_plugin_room_allowlist_authorizes_unlisted_sender(monkeypatch):
    """A listed LINE room is likewise a chat-level grant."""
    monkeypatch.setenv("LINE_ALLOWED_USERS", "U-owner")
    monkeypatch.delenv("LINE_ALLOWED_GROUPS", raising=False)
    monkeypatch.setenv("LINE_ALLOWED_ROOMS", "R-family")
    monkeypatch.delenv("GATEWAY_ALLOWED_USERS", raising=False)
    line = _register_line(monkeypatch)

    assert _runner_for(line, extra={"authorize_allowed_chats": True})._is_user_authorized(
        _source(line, chat_type="room", chat_id="R-family", user_id="U-someone-else")
    ) is True
