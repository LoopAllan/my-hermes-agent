"""Long-running heartbeat privacy contracts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from gateway.config import Platform
from gateway.display_config import resolve_display_setting
from gateway.run_turn import GatewayTurnMixin


@pytest.mark.asyncio
@pytest.mark.parametrize("detail", [None, False])
async def test_heartbeat_without_literal_true_detail_is_elapsed_only(monkeypatch, detail):
    """Default and false detail never reveal agent activity or await a phrase provider."""
    monkeypatch.setenv("HERMES_AGENT_NOTIFY_INTERVAL", "1")
    monkeypatch.setattr("gateway.run_turn.asyncio.sleep", AsyncMock())
    adapter = SimpleNamespace(
        send=AsyncMock(return_value=SimpleNamespace(success=True, message_id="heartbeat")),
        edit_message=AsyncMock(return_value=SimpleNamespace(success=True)),
    )
    activity = Mock(return_value={
        "api_call_count": 7,
        "max_iterations": 100,
        "current_tool": "private-tool",
        "last_activity_desc": "private-activity",
    })
    runner = SimpleNamespace(
        _delivery_adapter_for=lambda source: adapter,
        _should_emit_long_running_notification=lambda *args: adapter.edit_message.await_count == 0,
        _agent_activity_summary=activity,
    )
    config = {} if detail is None else {"display": {"busy_ack_detail": detail}}
    disp = SimpleNamespace(
        _display_surface_mode=lambda *args, **kwargs: "full",
        user_config=config,
        platform_key="telegram",
        resolve_display_setting=resolve_display_setting,
        _generic_status_phrase=lambda kind: "generic",
    )
    ctx = SimpleNamespace(
        source=SimpleNamespace(chat_id="chat", platform=Platform.TELEGRAM),
        session_key="session",
        agent_holder=[object()],
        _status_thread_metadata=None,
        _cleanup_progress=True,
        _cleanup_msg_ids=[],
    )

    await GatewayTurnMixin._run_agent_notify_long_running(runner, disp, ctx, [None])

    adapter.send.assert_awaited_once()
    adapter.edit_message.assert_awaited_once()
    for text in (adapter.send.await_args.args[1], adapter.edit_message.await_args.args[2]):
        assert text.startswith("⏳ Working — ") and text.endswith(" min")
        assert "private" not in text
        assert "configured" not in text
    activity.assert_not_called()
    assert ctx._cleanup_msg_ids == ["heartbeat"]


@pytest.mark.asyncio
async def test_heartbeat_detail_requires_literal_true(monkeypatch):
    """Only the literal boolean True enables the existing iteration detail."""
    monkeypatch.setenv("HERMES_AGENT_NOTIFY_INTERVAL", "1")
    monkeypatch.setattr("gateway.run_turn.asyncio.sleep", AsyncMock())
    adapter = SimpleNamespace(
        send=AsyncMock(return_value=SimpleNamespace(success=True, message_id="heartbeat")),
        edit_message=AsyncMock(return_value=SimpleNamespace(success=True)),
    )
    activity = Mock(return_value={"api_call_count": 7, "max_iterations": 100, "current_tool": "private-tool"})
    runner = SimpleNamespace(
        _delivery_adapter_for=lambda source: adapter,
        _should_emit_long_running_notification=lambda *args: adapter.edit_message.await_count == 0,
        _agent_activity_summary=activity,
    )
    disp = SimpleNamespace(
        _display_surface_mode=lambda *args, **kwargs: "full",
        user_config={"display": {"busy_ack_detail": True}},
        platform_key="telegram",
        resolve_display_setting=resolve_display_setting,
        _generic_status_phrase=lambda kind: "generic",
    )
    ctx = SimpleNamespace(
        source=SimpleNamespace(chat_id="chat", platform=Platform.TELEGRAM), session_key="session",
        agent_holder=[object()], _status_thread_metadata=None, _cleanup_progress=True, _cleanup_msg_ids=[],
    )

    await GatewayTurnMixin._run_agent_notify_long_running(runner, disp, ctx, [None])

    assert "private-tool" in adapter.send.await_args.args[1]
    activity.assert_called()


@pytest.mark.asyncio
async def test_explicit_status_catalog_controls_default_heartbeat(monkeypatch):
    """A documented custom catalog wins without requiring the generic mode."""
    monkeypatch.setenv("HERMES_AGENT_NOTIFY_INTERVAL", "1")
    monkeypatch.setattr("gateway.run_turn.asyncio.sleep", AsyncMock())
    adapter = SimpleNamespace(
        send=AsyncMock(return_value=SimpleNamespace(success=True, message_id="heartbeat")),
        edit_message=AsyncMock(return_value=SimpleNamespace(success=True)),
    )
    runner = SimpleNamespace(
        _delivery_adapter_for=lambda source: adapter,
        _should_emit_long_running_notification=lambda *args: adapter.edit_message.await_count == 0,
        _agent_activity_summary=Mock(),
    )
    disp = SimpleNamespace(
        _display_surface_mode=lambda *args, **kwargs: "raw",
        user_config={"display": {"status_phrases": {"status": ["configured"]}}},
        platform_key="telegram",
        resolve_display_setting=resolve_display_setting,
        _generic_status_phrase=lambda kind: "configured",
        _custom_status_phrases_configured=True,
    )
    ctx = SimpleNamespace(
        source=SimpleNamespace(chat_id="chat", platform=Platform.TELEGRAM), session_key="session",
        agent_holder=[object()], _status_thread_metadata=None, _cleanup_progress=False, _cleanup_msg_ids=[],
    )

    await GatewayTurnMixin._run_agent_notify_long_running(runner, disp, ctx, [None])

    assert adapter.send.await_args.args[1] == "configured"
    assert adapter.edit_message.await_args.args[2] == "configured"
