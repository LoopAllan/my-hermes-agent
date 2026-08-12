"""Optional auxiliary-model gateway heartbeat generator."""

from __future__ import annotations

import re
from typing import Any

_MAX_LENGTH = 160


def _configured_language() -> str | None:
    """Return an explicitly configured status-generator language, if any."""
    from hermes_cli.config import load_config

    task = ((load_config().get("auxiliary") or {}).get("status_phrase_generation") or {})
    language = task.get("language") if isinstance(task, dict) else None
    return str(language).strip() if language else None


def _valid_sentence(content: Any, language: str) -> str | None:
    """Accept only one short, label-free sentence in the configured language."""
    if not isinstance(content, str):
        return None
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    if len(lines) != 1:
        return None
    sentence = lines[0].strip("`\"'").strip()
    if (
        not sentence
        or len(sentence) > _MAX_LENGTH
        or re.match(r"^(?:[-*•‣◦]|\d+[.)])", sentence)
        or ":" in sentence
        or "：" in sentence
        or len(re.findall(r"[.!?。！？]", sentence)) != 1
        or sentence[-1] not in ".!?。！？"
    ):
        return None
    has_han = bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", sentence))
    has_kana_or_hangul = bool(re.search(r"[\u3040-\u30ff\uac00-\ud7af]", sentence))
    normalized = language.casefold().replace("_", "-").strip()
    if normalized in {"english", "en", "en-us", "en-gb"}:
        return sentence if re.search(r"[A-Za-z]", sentence) and not has_han and not has_kana_or_hangul else None
    if normalized in {"traditional chinese", "traditional chinese (taiwan)", "chinese (traditional)", "zh-tw", "zh-hant"}:
        return sentence if has_han and not has_kana_or_hangul else None
    return None


async def generate_status_phrase() -> str | None:
    """Generate a generic heartbeat, or return None to retain the native heartbeat."""
    try:
        language = _configured_language()
        if not language:
            return None
        from agent.auxiliary_client import async_call_llm

        response = await async_call_llm(
            task="status_phrase_generation",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Return exactly one short, natural chat status sentence saying the assistant is still "
                        f"working and will reply when finished. Write in {language}. Do not mention time, tools, "
                        "task details, errors, or hidden work. Return only the sentence."
                    ),
                }
            ],
            temperature=0.9,
            max_tokens=64,
        )
        return _valid_sentence(response.choices[0].message.content, language)
    except Exception:
        return None
