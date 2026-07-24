"""Append-only archive for LINE group/room messages that arrive without an
@mention of the bot.

When ``require_mention`` is on, the LINE adapter drops un-@'d group/room
messages before they ever reach the agent (see ``_dispatch_event``). Those
messages would otherwise be lost. This module persists them, one JSON object
per line, so they can be reviewed or analysed later.

Design notes:
  * Single responsibility — this module only knows how to append a record to a
    JSONL file. The decision of *what* counts as archivable lives in the
    adapter.
  * Best-effort — archiving must never break message handling. Every failure is
    swallowed with a warning; callers can rely on this never raising.
  * Atomic append — a single ``O_APPEND`` write is atomic on POSIX, so
    concurrent writers (multiple gateway tasks) never interleave a line. A
    process-local lock serialises writes within one process too.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Serialise writes within this process. Cross-process safety comes from O_APPEND.
_write_lock = threading.Lock()

# Default archive location, resolved lazily so HERMES_HOME overrides are honored.
_DEFAULT_SUBPATH = ("logs", "line-unmentioned.jsonl")


def _resolve_path(path: Optional[str]) -> Path:
    """Resolve the archive file path.

    An explicit ``path`` (from config) wins; relative paths resolve against the
    Hermes home dir, matching the project-wide convention. With no path, fall
    back to ``<hermes_home>/logs/line-unmentioned.jsonl``.
    """
    if path:
        p = Path(path).expanduser()
        if p.is_absolute():
            return p
        from hermes_constants import get_hermes_home

        return get_hermes_home() / p

    from hermes_constants import get_hermes_home

    return get_hermes_home().joinpath(*_DEFAULT_SUBPATH)


def append_unmentioned_record(record: dict, *, path: Optional[str] = None) -> None:
    """Append ``record`` as one JSON line to the archive file.

    Never raises — archiving is a side effect that must not disturb the inbound
    message path. The ``text`` field is passed through the credential redactor
    so an accidentally-pasted secret is not persisted verbatim.
    """
    try:
        # Redact the message body — a user may paste a token into a group chat.
        if isinstance(record.get("text"), str):
            try:
                from agent.redact import redact_sensitive_text

                record = {**record, "text": redact_sensitive_text(record["text"], force=True)}
            except Exception:
                pass  # redaction is best-effort; never block archiving on it

        target = _resolve_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"

        with _write_lock:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, line.encode("utf-8"))
            finally:
                os.close(fd)
    except Exception as exc:  # noqa: BLE001 — best-effort sink, must not propagate
        logger.warning("LINE: failed to archive unmentioned message: %s", exc)
