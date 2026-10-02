"""Regression tests for session-scoped model/provider overrides in gateway agents.

These cover the bug where `/model ...` stored a session override, but fresh
agent constructions still resolved model/provider from global config/runtime.
That let helper agents (and cache-miss main agents) route GPT-5.4 to the wrong
provider, e.g. Nous instead of OpenAI Codex.
"""

import asyncio
import sys
import threading
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

import gateway.run as gateway_run
from gateway.config import Platform
from gateway.platforms.event import MessageEvent
from gateway.session import SessionSource


class _CapturingAgent:
    """Fake agent that records init kwargs for assertions."""

    last_init = None

    def __init__(self, *args, **kwargs):
        type(self).last_init = dict(kwargs)
        self.tools = []

    def run_conversation(self, user_message: str, conversation_history=None, task_id=None, **_turn_kwargs):
        return {
            "final_response": "ok",
            "messages": [],
            "api_calls": 1,
        }


def _make_runner():
    runner = object.__new__(gateway_run.GatewayRunner)
    runner.adapters = {}
    runner.session_store = None
    runner.config = None
    runner._voice_mode = {}
    runner._ephemeral_system_prompt = ""
    runner._prefill_messages = []
    runner._reasoning_config = None
    runner._show_reasoning = False
    runner._provider_routing = {}
    runner._fallback_model = None
    runner._service_tier = None
    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner._background_tasks = set()
    runner._session_db = None
    runner._session_model_overrides = {}
    runner._session_reasoning_overrides = {}
    runner._pending_model_notes = {}
    runner._pending_approvals = {}
    runner._agent_cache = {}
    runner._agent_cache_lock = threading.Lock()
    runner._get_or_create_gateway_honcho = lambda session_key: (None, None)
    runner.hooks = MagicMock()
    runner.hooks.emit = AsyncMock()
    runner.hooks.loaded_hooks = []
    return runner


def _codex_override():
    return {
        "model": "gpt-5.4",
        "provider": "openai-codex",
        "api_key": "***",
        "base_url": "https://chatgpt.com/backend-api/codex",
        "api_mode": "codex_responses",
    }


def _explode_runtime_resolution():
    raise AssertionError(
        "global runtime resolution should not run when a complete session override exists"
    )


def test_run_agent_prefers_session_override_over_global_runtime(monkeypatch):
    monkeypatch.setattr(gateway_run, "_load_gateway_config", lambda: {})
    monkeypatch.setattr(gateway_run, "_resolve_runtime_agent_kwargs", _explode_runtime_resolution)

    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = _CapturingAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)

    _CapturingAgent.last_init = None
    runner = _make_runner()

    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )
    session_key = "agent:main:local:dm"
    runner._session_model_overrides[session_key] = _codex_override()
    runner._session_reasoning_overrides[session_key] = {"enabled": True, "effort": "high"}

    result = asyncio.run(
        runner._run_agent(
            message="ping",
            context_prompt="",
            history=[],
            source=source,
            session_id="session-1",
            session_key=session_key,
        )
    )

    assert result["final_response"] == "ok"
    assert _CapturingAgent.last_init is not None
    assert _CapturingAgent.last_init["model"] == "gpt-5.4"
    assert _CapturingAgent.last_init["provider"] == "openai-codex"
    assert _CapturingAgent.last_init["api_mode"] == "codex_responses"
    assert _CapturingAgent.last_init["base_url"] == "https://chatgpt.com/backend-api/codex"
    assert _CapturingAgent.last_init["api_key"] == "***"
    assert _CapturingAgent.last_init["reasoning_config"] == {"enabled": True, "effort": "high"}


def test_run_agent_applies_message_alias_to_current_turn(monkeypatch):
    monkeypatch.setattr(
        gateway_run,
        "_load_gateway_config",
        lambda: {"model": {"message_aliases": {"Sol": {"model": "gpt5.6-sol"}}}},
    )
    monkeypatch.setattr(gateway_run, "_resolve_runtime_agent_kwargs", _explode_runtime_resolution)

    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = _CapturingAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)

    _CapturingAgent.last_init = None
    runner = _make_runner()
    runner._sync_session_model_from_agent = MagicMock()
    source = SessionSource(
        platform=Platform.LOCAL,
        chat_id="cli",
        chat_name="CLI",
        chat_type="dm",
        user_id="user-1",
    )
    session_key = "agent:main:local:dm"
    runner._session_model_overrides[session_key] = _codex_override()

    result = asyncio.run(
        runner._run_agent(
            message="Sol, inspect the error logs.",
            context_prompt="",
            history=[],
            source=source,
            session_id="session-1",
            session_key=session_key,
        )
    )

    assert result["final_response"] == "ok"
    assert _CapturingAgent.last_init["model"] == "gpt5.6-sol"
    assert _CapturingAgent.last_init["provider"] == "openai-codex"
    runner._sync_session_model_from_agent.assert_not_called()


def test_one_turn_alias_keeps_the_sessions_warm_agent_cached(monkeypatch):
    """An aliased turn runs on its own agent; the session's cached agent (prompt-cache prefix) survives."""
    monkeypatch.setattr(
        gateway_run,
        "_load_gateway_config",
        lambda: {"model": {"message_aliases": {"Sol": {"model": "gpt5.6-sol"}}}},
    )
    monkeypatch.setattr(gateway_run, "_resolve_runtime_agent_kwargs", _explode_runtime_resolution)
    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = _CapturingAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)
    runner = _make_runner()
    runner._sync_session_model_from_agent = MagicMock()
    released = []
    monkeypatch.setattr(runner, "_release_evicted_agent_soft", released.append)
    source = SessionSource(platform=Platform.LOCAL, chat_id="cli", chat_name="CLI", chat_type="dm", user_id="user-1")
    session_key = "agent:main:local:dm"
    runner._session_model_overrides[session_key] = _codex_override()
    warm = (object(), "warm-signature", 0, "session-1")
    runner._agent_cache[session_key] = warm

    asyncio.run(runner._run_agent(
        message="Sol, inspect the error logs.", context_prompt="", history=[], source=source,
        session_id="session-1", session_key=session_key,
    ))

    assert _CapturingAgent.last_init["model"] == "gpt5.6-sol"
    assert runner._agent_cache[session_key] is warm
    assert len(released) == 1 and isinstance(released[0], _CapturingAgent)


def test_one_turn_alias_agent_is_released_when_the_turn_raises(monkeypatch):
    """The uncached alias agent is released on every exit, not only after a clean turn."""
    monkeypatch.setattr(
        gateway_run,
        "_load_gateway_config",
        lambda: {"model": {"message_aliases": {"Sol": {"model": "gpt5.6-sol"}}}},
    )
    monkeypatch.setattr(gateway_run, "_resolve_runtime_agent_kwargs", _explode_runtime_resolution)

    class _FailingAgent(_CapturingAgent):
        def run_conversation(self, *args, **kwargs):
            raise RuntimeError("provider exploded")

    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = _FailingAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)
    runner = _make_runner()
    runner._sync_session_model_from_agent = MagicMock()
    released = []
    monkeypatch.setattr(runner, "_release_evicted_agent_soft", released.append)
    source = SessionSource(platform=Platform.LOCAL, chat_id="cli", chat_name="CLI", chat_type="dm", user_id="user-1")
    session_key = "agent:main:local:dm"
    runner._session_model_overrides[session_key] = _codex_override()

    try:
        asyncio.run(runner._run_agent(
            message="Sol, inspect the error logs.", context_prompt="", history=[], source=source,
            session_id="session-1", session_key=session_key,
        ))
    except RuntimeError:
        pass

    assert len(released) == 1 and isinstance(released[0], _FailingAgent)


def test_provider_alias_still_answers_when_the_base_route_is_unavailable(monkeypatch):
    """Expired default credentials must not block an alias that names a working provider."""
    monkeypatch.setattr(
        gateway_run,
        "_load_gateway_config",
        lambda: {"model": {"message_aliases": {"Luna": {"model": "moonshot/kimi-k3", "provider": "openrouter"}}}},
    )

    def expired_default_login():
        raise RuntimeError("openai-codex login expired")

    monkeypatch.setattr(gateway_run, "_resolve_runtime_agent_kwargs", expired_default_login)
    monkeypatch.setattr(
        gateway_run, "_resolve_runtime_agent_kwargs_for_provider",
        lambda provider, target_model=None: {
            "provider": provider, "api_key": "or-key", "base_url": "https://openrouter.ai/api/v1",
            "api_mode": "chat_completions", "credential_pool": None, "request_overrides": {}, "capabilities": {}},
    )
    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = _CapturingAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)
    _CapturingAgent.last_init = None
    runner = _make_runner()
    runner._sync_session_model_from_agent = MagicMock()
    source = SessionSource(platform=Platform.LOCAL, chat_id="cli", chat_name="CLI", chat_type="dm", user_id="user-1")

    result = asyncio.run(runner._run_agent(
        message="Luna, summarize this.", context_prompt="", history=[], source=source,
        session_id="session-1", session_key="agent:main:local:dm",
    ))

    assert result["final_response"] == "ok"
    assert _CapturingAgent.last_init["provider"] == "openrouter"
    assert _CapturingAgent.last_init["model"] == "moonshot/kimi-k3"


def test_message_alias_with_provider_routes_through_that_provider(monkeypatch):
    """An alias for another provider's model gets that provider's full route, like channel_overrides."""
    monkeypatch.setattr(
        gateway_run,
        "_load_gateway_config",
        lambda: {"model": {"message_aliases": {"Luna": {"model": "moonshot/kimi-k3", "provider": "openrouter"}}}},
    )
    monkeypatch.setattr(gateway_run, "_resolve_runtime_agent_kwargs", _explode_runtime_resolution)
    routed = []

    def resolve_for_provider(provider, target_model=None):
        routed.append((provider, target_model))
        return {"provider": provider, "api_key": "or-key", "base_url": "https://openrouter.ai/api/v1",
                "api_mode": "chat_completions", "credential_pool": None,
                "request_overrides": {}, "capabilities": {}}

    monkeypatch.setattr(gateway_run, "_resolve_runtime_agent_kwargs_for_provider", resolve_for_provider)
    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = _CapturingAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)
    _CapturingAgent.last_init = None
    runner = _make_runner()
    runner._sync_session_model_from_agent = MagicMock()
    source = SessionSource(platform=Platform.LOCAL, chat_id="cli", chat_name="CLI", chat_type="dm", user_id="user-1")
    session_key = "agent:main:local:dm"
    runner._session_model_overrides[session_key] = _codex_override()

    asyncio.run(runner._run_agent(
        message="Luna, summarize this.", context_prompt="", history=[], source=source,
        session_id="session-1", session_key=session_key,
    ))

    assert routed[-1] == ("openrouter", "moonshot/kimi-k3")
    assert _CapturingAgent.last_init["model"] == "moonshot/kimi-k3"
    assert _CapturingAgent.last_init["provider"] == "openrouter"
    assert _CapturingAgent.last_init["base_url"] == "https://openrouter.ai/api/v1"
    runner._sync_session_model_from_agent.assert_not_called()


@pytest.mark.parametrize(
    ("authored", "expanded", "expected_model"),
    [
        ("/review the logs", "[skill scaffold: ask Sol for a second opinion]\n\nthe logs", "gpt-5.4"),
        ("Sol, /review the logs", "[skill scaffold]\n\nthe logs", "gpt5.6-sol"),
    ],
)
def test_message_alias_matches_only_user_authored_text(monkeypatch, authored, expanded, expected_model):
    """Skill scaffolds and media enrichment are not the user's words; only what they typed picks a model."""
    from gateway.message_model_aliases import remember_user_authored_text

    monkeypatch.setattr(
        gateway_run,
        "_load_gateway_config",
        lambda: {"model": {"message_aliases": {"Sol": {"model": "gpt5.6-sol"}}}},
    )
    monkeypatch.setattr(gateway_run, "_resolve_runtime_agent_kwargs", _explode_runtime_resolution)
    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = _CapturingAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)
    _CapturingAgent.last_init = None
    runner = _make_runner()
    runner._sync_session_model_from_agent = MagicMock()
    source = SessionSource(platform=Platform.LOCAL, chat_id="cli", chat_name="CLI", chat_type="dm", user_id="user-1")
    session_key = "agent:main:local:dm"
    runner._session_model_overrides[session_key] = _codex_override()
    remember_user_authored_text(MessageEvent(text=authored, source=source, message_id="inbound-1"))

    asyncio.run(runner._run_agent(
        message=expanded, context_prompt="", history=[], source=source,
        session_id="session-1", session_key=session_key, inbound_message_id="inbound-1",
    ))

    assert _CapturingAgent.last_init["model"] == expected_model


@pytest.mark.asyncio
async def test_background_task_prefers_session_override_over_global_runtime(monkeypatch):
    monkeypatch.setattr(gateway_run, "_load_gateway_config", lambda: {})
    monkeypatch.setattr(gateway_run, "_resolve_runtime_agent_kwargs", _explode_runtime_resolution)

    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = _CapturingAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)

    _CapturingAgent.last_init = None
    runner = _make_runner()

    adapter = AsyncMock()
    adapter.send = AsyncMock()
    adapter.extract_media = MagicMock(return_value=([], "ok"))
    adapter.extract_images = MagicMock(return_value=([], "ok"))
    runner.adapters[Platform.TELEGRAM] = adapter

    source = SessionSource(
        platform=Platform.TELEGRAM,
        user_id="12345",
        chat_id="67890",
        user_name="testuser",
    )
    session_key = runner._session_key_for_source(source)
    runner._session_model_overrides[session_key] = _codex_override()
    runner._session_reasoning_overrides[session_key] = {"enabled": True, "effort": "high"}

    await runner._run_background_task("say hello", source, "bg_test")

    assert _CapturingAgent.last_init is not None
    assert _CapturingAgent.last_init["model"] == "gpt-5.4"
    assert _CapturingAgent.last_init["provider"] == "openai-codex"
    assert _CapturingAgent.last_init["api_mode"] == "codex_responses"
    assert _CapturingAgent.last_init["base_url"] == "https://chatgpt.com/backend-api/codex"
    assert _CapturingAgent.last_init["api_key"] == "***"
    assert _CapturingAgent.last_init["reasoning_config"] == {"enabled": True, "effort": "high"}


@pytest.mark.asyncio
async def test_background_task_applies_message_alias_to_current_turn(monkeypatch):
    monkeypatch.setattr(
        gateway_run,
        "_load_gateway_config",
        lambda: {"model": {"message_aliases": {"Sol": {"model": "gpt5.6-sol"}}}},
    )
    monkeypatch.setattr(gateway_run, "_resolve_runtime_agent_kwargs", _explode_runtime_resolution)

    fake_run_agent = types.ModuleType("run_agent")
    fake_run_agent.AIAgent = _CapturingAgent
    monkeypatch.setitem(sys.modules, "run_agent", fake_run_agent)

    _CapturingAgent.last_init = None
    runner = _make_runner()
    adapter = AsyncMock()
    adapter.send = AsyncMock()
    adapter.extract_media = MagicMock(return_value=([], "ok"))
    adapter.extract_images = MagicMock(return_value=([], "ok"))
    runner.adapters[Platform.TELEGRAM] = adapter
    source = SessionSource(
        platform=Platform.TELEGRAM,
        user_id="12345",
        chat_id="67890",
        user_name="testuser",
    )
    session_key = runner._session_key_for_source(source)
    runner._session_model_overrides[session_key] = _codex_override()

    await runner._run_background_task("Sol, inspect the error logs.", source, "bg_test")

    assert _CapturingAgent.last_init is not None
    assert _CapturingAgent.last_init["model"] == "gpt5.6-sol"
    assert _CapturingAgent.last_init["provider"] == "openai-codex"


def test_gateway_auth_fallback_uses_fallback_model_from_config(tmp_path, monkeypatch):
    """Regression: fallback provider must not inherit the primary model.

    If primary openai-codex auth fails and fallback_providers selects
    OpenRouter/minimax, the gateway must instantiate AIAgent with the fallback
    model, not the primary config model (e.g. gpt-5.5). Otherwise OpenRouter
    receives an unintended GPT request.
    """
    config = tmp_path / "config.yaml"
    config.write_text(
        """
model:
  default: gpt-5.5
  provider: openai-codex
fallback_providers:
  - provider: openrouter
    model: minimax/minimax-m2.7
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)

    def fake_resolve_runtime_provider(*, requested=None, explicit_base_url=None, explicit_api_key=None,
                                      target_model=None):
        if requested in {None, "", "openai-codex"}:
            from hermes_cli.auth import AuthError
            raise AuthError("No Codex credentials stored. Run `hermes auth` to authenticate.")
        assert requested == "openrouter"
        # The fallback rung is resolved against the model it will send, not the primary default.
        assert target_model == "minimax/minimax-m2.7"
        return {
            "api_key": "sk-openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "provider": "openrouter",
            "api_mode": "chat_completions",
            "command": None,
            "args": [],
            "credential_pool": None,
        }

    import hermes_cli.runtime_provider as runtime_provider

    monkeypatch.setattr(runtime_provider, "resolve_runtime_provider", fake_resolve_runtime_provider)

    runner = _make_runner()
    model, runtime_kwargs = runner._resolve_session_agent_runtime(
        session_key="agent:main:telegram:group:-1003715515980:63",
        user_config={
            "model": {"default": "gpt-5.5", "provider": "openai-codex"},
            "fallback_providers": [{"provider": "openrouter", "model": "minimax/minimax-m2.7"}],
        },
    )

    assert model == "minimax/minimax-m2.7"
    assert runtime_kwargs["provider"] == "openrouter"
    assert runtime_kwargs["api_key"] == "sk-openrouter"


