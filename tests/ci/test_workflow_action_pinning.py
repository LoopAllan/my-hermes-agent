"""Every external GitHub Action is pinned to a full commit SHA (dependency pinning policy, #9801).

A mutable tag in a job holding ``packages: write`` or a deploy credential runs whatever the tag
points at next; a malformed SHA fails the job only when that step finally runs on ``main``.
"""
import re
from pathlib import Path

import hermes_yaml as yaml

ROOT = Path(__file__).resolve().parents[2]
_PINNED = re.compile(r"^[^@\s]+@[0-9a-f]{40}$")


def _uses(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "uses" and isinstance(child, str):
                yield child
            else:
                yield from _uses(child)
    elif isinstance(value, list):
        for child in value:
            yield from _uses(child)


def test_external_actions_are_pinned_to_full_commit_shas():
    unpinned = []
    for path in sorted((ROOT / ".github").rglob("*")):
        if path.suffix not in {".yml", ".yaml"}:
            continue
        for ref in _uses(yaml.safe_load(path.read_text(encoding="utf-8-sig"))):
            if ref.startswith(("./", "docker://")):
                continue
            if not _PINNED.match(ref):
                unpinned.append(f"{path.relative_to(ROOT)}: {ref}")
    assert not unpinned, "\n".join(unpinned)
