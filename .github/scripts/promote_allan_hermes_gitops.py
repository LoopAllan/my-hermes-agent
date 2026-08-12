#!/usr/bin/env python3
"""Pin the Allan Hermes GitOps profile to a verified immutable image digest."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PROFILE_IMAGE = re.compile(
    r"(?ms)^  image:\n"
    r"(?=^(?:    [^\n]*\n)*?    repository: ghcr\.io/loopallan/allan-hermes-agent$)"
    r"(?:    [^\n]*\n)*?"
    r"^(?P<prefix>    digest: )(?P<current>sha256:[0-9a-f]{64})$"
)


def pin_digest(path: Path, digest: str) -> bool:
    """Replace exactly the Allan Hermes profile digest, returning whether it changed."""
    if not _DIGEST.fullmatch(digest):
        raise ValueError("image digest must be sha256 followed by 64 lowercase hex characters")
    if not path.is_file():
        raise FileNotFoundError(f"required GitOps profile is missing: {path}")

    content = path.read_text(encoding="utf-8")
    match = _PROFILE_IMAGE.search(content)
    if not match or len(_PROFILE_IMAGE.findall(content)) != 1:
        raise ValueError("expected exactly one allan-hermes-agent profile image digest")
    if match.group("current") == digest:
        return False

    updated = content[:match.start("current")] + digest + content[match.end("current"):]
    path.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--digest", required=True)
    args = parser.parse_args()

    print("updated" if pin_digest(args.profile, args.digest) else "unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
