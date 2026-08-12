#!/usr/bin/env python3
"""Pin the Allan Hermes GitOps profile to a verified immutable image digest."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_IMAGE_BLOCK = re.compile(r"(?m)^  image:\n(?P<body>(?:^    [^\n]*\n?)*)")
_EXPECTED_REPOSITORY = "ghcr.io/loopallan/allan-hermes-agent"


def _profile_image_digest(content: str) -> tuple[int, int, str]:
    """Return the one unambiguous Allan Hermes profile digest location and value."""
    candidates = []
    for block in _IMAGE_BLOCK.finditer(content):
        body = block.group("body")
        repositories = re.findall(r"(?m)^    repository: ([^\n]+)$", body)
        if repositories != [_EXPECTED_REPOSITORY]:
            continue
        digests = list(re.finditer(r"(?m)^    digest: (sha256:[0-9a-f]{64})$", body))
        if len(digests) != 1:
            raise ValueError("expected exactly one allan-hermes-agent profile image digest")
        candidates.append((block.start("body") + digests[0].start(1), block.start("body") + digests[0].end(1)))

    if len(candidates) != 1:
        raise ValueError("expected exactly one allan-hermes-agent profile image digest")
    start, end = candidates[0]
    return start, end, content[start:end]


def pin_digest(path: Path, digest: str) -> bool:
    """Replace exactly the Allan Hermes profile digest, returning whether it changed."""
    if not _DIGEST.fullmatch(digest):
        raise ValueError("image digest must be sha256 followed by 64 lowercase hex characters")
    if not path.is_file():
        raise FileNotFoundError(f"required GitOps profile is missing: {path}")

    content = path.read_text(encoding="utf-8")
    for block in _IMAGE_BLOCK.finditer(content):
        body = block.group("body")
        if re.findall(r"(?m)^    repository: ([^\n]+)$", body) == [_EXPECTED_REPOSITORY]:
            if len(re.findall(r"(?m)^    digest:", body)) != 1:
                raise ValueError("duplicate YAML key: digest")
    start, end, current_digest = _profile_image_digest(content)
    if current_digest == digest:
        return False

    updated = content[:start] + digest + content[end:]
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
