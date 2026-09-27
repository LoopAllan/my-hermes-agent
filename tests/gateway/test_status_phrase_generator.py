import pytest

from gateway.status_phrase_generator import generate_status_phrase


@pytest.mark.asyncio
async def test_generate_selects_trimmed_phrase_from_environment(monkeypatch):
    monkeypatch.setenv(
        "HEART_BEAT_WORKING_PHASES",
        "  我還在處理中，完成後回覆你。 , ,請稍等，我整理好就回覆你。  ",
    )

    phrase = await generate_status_phrase()

    assert phrase in {"我還在處理中，完成後回覆你。", "請稍等，我整理好就回覆你。"}


@pytest.mark.asyncio
async def test_generate_returns_none_without_usable_environment_phrases(monkeypatch):
    monkeypatch.setenv("HEART_BEAT_WORKING_PHASES", " ,  , ")

    assert await generate_status_phrase() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("detail", [None, False, True])
@pytest.mark.parametrize("phrase", ["", "我還在處理中。"])
async def test_native_heartbeat_opt_in_and_configured_phrase(monkeypatch, detail, phrase):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from gateway.config import Platform
    from gateway.display_config import resolve_display_setting
    from gateway.run_turn import GatewayTurnMixin

    monkeypatch.setenv("HEART_BEAT_WORKING_PHASES", phrase)
    monkeypatch.setenv("HERMES_AGENT_NOTIFY_INTERVAL", "1")
    monkeypatch.setattr("gateway.run_turn.asyncio.sleep", AsyncMock())
    adapter = SimpleNamespace(
        send=AsyncMock(return_value=SimpleNamespace(success=True, message_id="heartbeat")),
        edit_message=AsyncMock(return_value=SimpleNamespace(success=True)),
    )
    activity = Mock(return_value={"api_call_count": 7, "max_iterations": 100,
                                 "current_tool": "private-tool", "last_activity_desc": "private-activity"})
    runner = SimpleNamespace(
        _delivery_adapter_for=lambda source: adapter,
        _should_emit_long_running_notification=lambda *args: adapter.edit_message.await_count == 0,
        _agent_activity_summary=activity,
    )
    config = {} if detail is None else {"display": {"busy_ack_detail": detail}}
    disp = SimpleNamespace(
        _display_surface_mode=lambda *args, **kwargs: "full", user_config=config,
        platform_key="telegram", resolve_display_setting=resolve_display_setting,
        _generic_status_phrase=lambda kind: "generic",
    )
    ctx = SimpleNamespace(
        source=SimpleNamespace(chat_id="chat", platform=Platform.TELEGRAM), session_key="session",
        agent_holder=[object()], _status_thread_metadata=None,
        _cleanup_progress=True, _cleanup_msg_ids=[],
    )
    await GatewayTurnMixin._run_agent_notify_long_running(runner, disp, ctx, [None])
    adapter.send.assert_awaited_once()
    adapter.edit_message.assert_awaited_once()
    texts = [adapter.send.await_args.args[1], adapter.edit_message.await_args.args[2]]
    for text in texts:
        if phrase:
            assert text == phrase
        elif detail is True:
            assert "private-tool" in text and "7" in text
        else:
            assert text.startswith("⏳ Working — ") and text.endswith(" min")
            assert "private" not in text
    if detail is not True:
        activity.assert_not_called()
    assert ctx._cleanup_msg_ids == ["heartbeat"]
