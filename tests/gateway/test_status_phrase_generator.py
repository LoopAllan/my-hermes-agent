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


def test_native_heartbeat_does_not_append_internal_activity_label():
    source = ("\n".join(__import__("pathlib").Path("gateway/run.py").read_text().splitlines()))

    assert '_heartbeat_text = f"⏳ Working — {_elapsed_mins} min"' in source
    assert '_heartbeat_text = f"⏳ Working — {_elapsed_mins} min{_status_detail}"' not in source
