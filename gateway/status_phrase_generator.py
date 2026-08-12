"""Optional auxiliary-model gateway heartbeat generator."""

from __future__ import annotations

import re
from typing import Any

_MAX_LENGTH = 160
# Fail closed: a generated heartbeat may only express generic progress and a
# future reply. These are safety predicates, not response templates.
_FORBIDDEN_TERMS = re.compile(
    r"\b(?:password|secret|token|api[ -]?key|private|email|searched|tool|command|error|failed|failure)\b"
    r"|任務|錯誤|失敗|密碼|祕密|秘密|權杖|私密|信件|搜尋|工具|指令",
    re.IGNORECASE,
)
# A deliberately tiny permitted vocabulary makes leakage of model-invented
# project details fail closed. It defines safety classes, never fixed replies.
_ENGLISH_WORDS = frozenset({
    "i", "am", "i'm", "still", "working", "processing", "handling", "on", "it",
    "and", "will", "reply", "respond", "get", "back", "to", "you", "when", "once",
    "after", "soon", "later", "finished", "complete", "completed", "this", "is", "being",
})
_ZH_ALLOWED = frozenset("我你還仍正繼在處理進行整理中著完成功後稍之會回覆答應請等一下點事務")
_ENGLISH_PROGRESS = re.compile(r"\b(?:still\s+)?(?:working|handling|processing|continuing)\b|\bon\s+it\b", re.IGNORECASE)
_ENGLISH_REPLY = re.compile(r"\b(?:reply|respond|get\s+back)\b", re.IGNORECASE)
_ENGLISH_FUTURE = re.compile(r"\b(?:when|once|after|soon|later)\b", re.IGNORECASE)
_ZH_PROGRESS = re.compile(r"(?:還在|仍在|正在|繼續).{0,8}(?:處理|進行|整理)|(?:處理|進行|整理).{0,8}(?:中|著)")
_ZH_REPLY = re.compile(r"(?:回覆|答覆|回應)")
_ZH_FUTURE = re.compile(r"(?:完成後|稍後|之後|一會|待.{0,8}完成)")


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
    if _FORBIDDEN_TERMS.search(sentence):
        return None
    has_han = bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", sentence))
    has_kana_or_hangul = bool(re.search(r"[\u3040-\u30ff\uac00-\ud7af]", sentence))
    normalized = language.casefold().replace("_", "-").strip()
    if normalized in {"english", "en", "en-us", "en-gb"}:
        words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", sentence.casefold())
        if not (words and set(words) <= _ENGLISH_WORDS and not has_han and not has_kana_or_hangul):
            return None
        return sentence if _ENGLISH_PROGRESS.search(sentence) and _ENGLISH_REPLY.search(sentence) and _ENGLISH_FUTURE.search(sentence) else None
    if normalized in {"traditional chinese", "traditional chinese (taiwan)", "chinese (traditional)", "zh-tw", "zh-hant"}:
        han_chars = set(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", sentence))
        if not (han_chars and han_chars <= _ZH_ALLOWED and not has_kana_or_hangul):
            return None
        return sentence if _ZH_PROGRESS.search(sentence) and _ZH_REPLY.search(sentence) and _ZH_FUTURE.search(sentence) else None
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
