"""Contract tests for per-message gateway model aliases."""

from gateway.message_model_aliases import resolve_message_model_alias


def _config(aliases):
    return {"model": {"message_aliases": aliases}}


def test_matches_configured_alias_at_word_boundaries():
    resolved = resolve_message_model_alias(
        "Sol: review the latest deployment logs.",
        _config({"Sol": {"model": "gpt5.6-sol"}}),
    )

    assert resolved is not None
    assert resolved.alias == "Sol"
    assert resolved.model == "gpt5.6-sol"


def test_does_not_match_alias_inside_a_larger_word():
    assert resolve_message_model_alias(
        "Use console output rather than a Sol model.",
        _config({"Sol": {"model": "gpt5.6-sol"}}),
    ) is not None
    assert resolve_message_model_alias(
        "Use consoles output rather than a model.",
        _config({"Sol": {"model": "gpt5.6-sol"}}),
    ) is None


def test_matches_alias_case_insensitively():
    resolved = resolve_message_model_alias(
        "please use sol for this turn",
        _config({"Sol": {"model": "gpt5.6-sol"}}),
    )

    assert resolved is not None
    assert resolved.model == "gpt5.6-sol"


def test_uses_first_matching_configured_alias():
    resolved = resolve_message_model_alias(
        "Use Sol and Fast for this turn.",
        _config(
            {
                "Fast": {"model": "gpt5.6-fast"},
                "Sol": {"model": "gpt5.6-sol"},
            }
        ),
    )

    assert resolved is not None
    assert resolved.alias == "Fast"
    assert resolved.model == "gpt5.6-fast"


def test_ignores_invalid_alias_entries():
    assert resolve_message_model_alias(
        "Sol", _config({"Sol": {"provider": "openai-codex"}})
    ) is None


def test_alias_application_changes_only_this_turns_model():
    from gateway.message_model_aliases import apply_message_model_alias

    config = {
        "model": {
            "default": "openai/gpt-5.6-terra",
            "message_aliases": {"Sol": {"model": "gpt5.6-sol"}},
        }
    }
    runtime = {"provider": "openai"}

    assert apply_message_model_alias(
        "Sol, inspect the error logs.", "openai/gpt-5.6-terra", runtime, config
    ) == ("gpt5.6-sol", runtime)
    assert apply_message_model_alias(
        "Inspect the error logs.", "openai/gpt-5.6-terra", runtime, config
    ) == ("openai/gpt-5.6-terra", runtime)
    assert config["model"]["default"] == "openai/gpt-5.6-terra"


def test_user_authored_text_is_scoped_to_its_conversation():
    """Platform message ids repeat across chats (Telegram); one chat's text must never pick another's model."""
    from gateway.config import Platform
    from gateway.message_model_aliases import remember_user_authored_text, user_authored_text
    from gateway.platforms.event import MessageEvent
    from gateway.session import SessionSource

    first = SessionSource(platform=Platform.TELEGRAM, chat_id="chat-a", chat_type="group")
    second = SessionSource(platform=Platform.TELEGRAM, chat_id="chat-b", chat_type="group")
    remember_user_authored_text(MessageEvent(text="plain question", source=first, message_id="42"))
    remember_user_authored_text(MessageEvent(text="Sol, take this one", source=second, message_id="42"))

    assert user_authored_text(first, "42", "expanded") == "plain question"
    assert user_authored_text(second, "42", "expanded") == "Sol, take this one"


def test_aliases_reach_the_resolver_through_the_gateway_config_loader():
    """message_aliases written to config.yaml survive the effective gateway loader intact."""
    import hermes_yaml as yaml
    from gateway.run import _load_gateway_config
    from hermes_constants import get_hermes_home

    (get_hermes_home() / "config.yaml").write_text(yaml.safe_dump({
        "model": {
            "default": "anthropic/claude-opus-4.8",
            "message_aliases": {"Luna": {"model": "moonshot/kimi-k3", "provider": "openrouter"}},
        },
    }), encoding="utf-8")

    resolved = resolve_message_model_alias("Luna, summarize this.", _load_gateway_config())

    assert resolved is not None
    assert (resolved.model, resolved.provider) == ("moonshot/kimi-k3", "openrouter")
