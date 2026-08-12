#!/usr/bin/env python3
"""Pin the Allan Hermes GitOps profile to a verified immutable image digest."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import yaml
from yaml.constructor import ConstructorError

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_IMAGE_BLOCK = re.compile(r"(?m)^  image:\n(?P<body>(?:^    [^\n]*\n?)*)")
_EXPECTED_REPOSITORY = "ghcr.io/loopallan/allan-hermes-agent"


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate keys in every mapping."""


def _construct_unique_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConstructorError("while constructing a mapping", node.start_mark, f"duplicate YAML key: {key}", key_node.start_mark)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


def _validated_profile_image(content: str) -> dict[str, str]:
    """Parse the profile and verify the only image target accepted for promotion."""
    try:
        parsed = yaml.load(content, Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(parsed, dict):
        raise ValueError("GitOps profile must be a YAML mapping")
    profile = parsed.get("profile")
    if not isinstance(profile, dict):
        raise ValueError("GitOps profile must contain a profile mapping")
    image = profile.get("image")
    if not isinstance(image, dict) or image.get("repository") != _EXPECTED_REPOSITORY:
        raise ValueError("expected allan-hermes-agent profile image")
    current = image.get("digest")
    if not isinstance(current, str) or not _DIGEST.fullmatch(current):
        raise ValueError("expected exactly one allan-hermes-agent profile image digest")
    return {"digest": current}


def _profile_image_digest_location(content: str, current_digest: str) -> tuple[int, int]:
    """Find the validated digest's one text location without reserializing YAML."""
    matches: list[tuple[int, int]] = []
    for block in _IMAGE_BLOCK.finditer(content):
        body = block.group("body")
        if not re.search(r"(?m)^    repository\s*:\s*ghcr\.io/loopallan/allan-hermes-agent\s*$", body):
            continue
        for digest_match in re.finditer(r"(?m)^    digest\s*:\s*(sha256:[0-9a-f]{64})\s*$", body):
            if digest_match.group(1) == current_digest:
                matches.append((block.start("body") + digest_match.start(1), block.start("body") + digest_match.end(1)))
    if len(matches) != 1:
        raise ValueError("expected exactly one allan-hermes-agent profile image digest")
    return matches[0]


def pin_digest(path: Path, digest: str) -> bool:
    """Replace exactly the Allan Hermes profile digest, returning whether it changed."""
    if not _DIGEST.fullmatch(digest):
        raise ValueError("image digest must be sha256 followed by 64 lowercase hex characters")
    if not path.is_file():
        raise FileNotFoundError(f"required GitOps profile is missing: {path}")

    content = path.read_text(encoding="utf-8")
    current_digest = _validated_profile_image(content)["digest"]
    if current_digest == digest:
        return False
    start, end = _profile_image_digest_location(content, current_digest)
    path.write_text(content[:start] + digest + content[end:], encoding="utf-8")
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
