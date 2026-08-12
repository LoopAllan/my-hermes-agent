"""Regression tests for Allan Hermes direct GitOps promotion."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "promote_allan_hermes_gitops.py"
_spec = importlib.util.spec_from_file_location("promote_allan_hermes_gitops", _SCRIPT)
assert _spec and _spec.loader
promotion = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(promotion)


_PROFILE = """profile:
  image:
    repository: ghcr.io/loopallan/allan-hermes-agent
    tag: old
    digest: sha256:1111111111111111111111111111111111111111111111111111111111111111
    pullPolicy: IfNotPresent
"""


def test_pin_digest_replaces_only_the_profile_image_digest(tmp_path):
    profile = tmp_path / "allan-hermes-dev.yaml"
    profile.write_text(_PROFILE, encoding="utf-8")
    digest = "sha256:" + "a" * 64

    assert promotion.pin_digest(profile, digest) is True
    assert profile.read_text(encoding="utf-8") == _PROFILE.replace("1" * 64, "a" * 64)
    assert promotion.pin_digest(profile, digest) is False


def test_pin_digest_requires_the_gitops_profile_to_exist(tmp_path):
    with pytest.raises(FileNotFoundError, match="required GitOps profile is missing"):
        promotion.pin_digest(tmp_path / "missing.yaml", "sha256:" + "a" * 64)


@pytest.mark.parametrize(
    ("content", "digest", "error"),
    [
        (_PROFILE.replace("allan-hermes-agent", "wrong-image"), "sha256:" + "a" * 64, "expected exactly one"),
        (_PROFILE, "sha256:ABC", "image digest must be"),
    ],
)
def test_pin_digest_fails_closed_for_wrong_profile_or_digest(tmp_path, content, digest, error):
    profile = tmp_path / "allan-hermes-dev.yaml"
    profile.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        promotion.pin_digest(profile, digest)
