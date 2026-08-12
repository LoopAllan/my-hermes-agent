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


def test_gateway_alias_application_is_turn_scoped():
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner._session_model_overrides = {}
    config = {
        "model": {
            "default": "openai/gpt-5.6-terra",
            "message_aliases": {"Sol": {"model": "gpt5.6-sol"}},
        }
    }

    assert runner._apply_message_model_alias(
        "Sol, inspect the error logs.", "openai/gpt-5.6-terra", config
    ) == "gpt5.6-sol"
    assert runner._apply_message_model_alias(
        "Inspect the error logs.", "openai/gpt-5.6-terra", config
    ) == "openai/gpt-5.6-terra"
    assert runner._session_model_overrides == {}
