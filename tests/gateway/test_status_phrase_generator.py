from types import SimpleNamespace

import pytest

from gateway.status_phrase_generator import _valid_sentence, generate_status_phrase


@pytest.mark.parametrize(
    ("language", "content"),
    [
        ("English", "Still working and I will reply soon."),
        ("Traditional Chinese (Taiwan)", "我還在處理，完成後會回覆你。"),
    ],
)
def test_valid_sentence_accepts_configured_language(language, content):
    assert _valid_sentence(content, language) == content


@pytest.mark.parametrize(
    "content",
    [
        "Label: Still working.",
        "•Still working.",
        "1. Still working.",
        "Still working. I will reply soon.",
        "Still working and I will reply soon",
        "我還在處理，完成後會回覆你。",
        "My password is abc.",
        "I searched your private email.",
        "The task failed.",
        "I am still working, but the task failed and I will reply soon.",
        "I am still working on it.",
    ],
)
def test_valid_sentence_rejects_malformed_wrong_language_or_unsafe_content(content):
    assert _valid_sentence(content, "English") is None


@pytest.mark.asyncio
async def test_generate_returns_none_when_task_is_not_configured(monkeypatch):
    monkeypatch.setattr("hermes_cli.config.load_config", lambda: {"auxiliary": {}})

    assert await generate_status_phrase() is None


@pytest.mark.asyncio
async def test_generate_uses_existing_auxiliary_task_router(monkeypatch):
    monkeypatch.setattr(
        "hermes_cli.config.load_config",
        lambda: {"auxiliary": {"status_phrase_generation": {"language": "English"}}},
    )
    captured = {}

    async def fake_call_llm(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Still working and I will reply soon."))])

    monkeypatch.setattr("agent.auxiliary_client.async_call_llm", fake_call_llm)

    assert await generate_status_phrase() == "Still working and I will reply soon."
    assert captured["task"] == "status_phrase_generation"
    assert "task details" in captured["messages"][0]["content"]
