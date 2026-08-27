"""Regression tests for Allan Hermes direct GitOps promotion."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml


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


def test_workflow_runs_after_successful_main_base_image_publish():
    workflow_path = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "allan-hermes-agent-image.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    triggers = workflow[True]
    assert "push" not in triggers
    assert triggers["workflow_run"] == {
        "workflows": ["Publish Fork Image to GHCR"],
        "types": ["completed"],
    }

    assert workflow["concurrency"] == {
        "group": "allan-hermes-agent-main-release",
        "cancel-in-progress": False,
    }

    build_job = workflow["jobs"]["build-test-and-publish"]
    assert "workflow_run.conclusion == 'success'" in build_job["if"]
    assert "workflow_run.event == 'push'" in build_job["if"]
    assert "workflow_run.head_branch == 'main'" in build_job["if"]
    checkout = next(step for step in build_job["steps"] if step["name"] == "Checkout")
    assert checkout["with"]["ref"] == "${{ env.SOURCE_SHA }}"
    candidate = next(step for step in build_job["steps"] if step["name"] == "Build candidate image")
    assert candidate["with"]["build-args"] == "BASE_IMAGE=ghcr.io/loopallan/my-hermes-agent:${{ env.SOURCE_SHA }}"

    promotion_job = workflow["jobs"]["promote-gitops"]
    assert promotion_job["if"] == "github.event_name == 'workflow_run'"
    assert promotion_job["needs"] == "build-test-and-publish"
    assert promotion_job["environment"] == "ALLAN_APPS_GITOPS_TOKEN"
    pull_step = next(step for step in promotion_job["steps"] if step["name"] == "Pull published image")
    assert pull_step["run"] == 'docker pull "$IMAGE_NAME:${SOURCE_SHA}"'
    promotion_step = next(step for step in promotion_job["steps"] if step["name"] == "Promote immutable image digest to Allan GitOps")
    assert 'docker run --rm --entrypoint python3 --user "$(id -u):$(id -g)"' in promotion_step["run"]
    assert '"$IMAGE_NAME:${SOURCE_SHA}" \\\n    /tmp/promote_allan_hermes_gitops.py' in promotion_step["run"]


@pytest.mark.parametrize(
    ("content", "digest", "error"),
    [
        (_PROFILE.replace("allan-hermes-agent", "wrong-image"), "sha256:" + "a" * 64, "expected allan-hermes-agent profile image"),
        (_PROFILE.replace("    pullPolicy", "    digest: sha256:" + "2" * 64 + "\n    pullPolicy"), "sha256:" + "a" * 64, "duplicate YAML key: digest"),
        (_PROFILE.replace("    pullPolicy", "    digest : sha256:" + "2" * 64 + "\n    pullPolicy"), "sha256:" + "a" * 64, "duplicate YAML key: digest"),
        (_PROFILE, "sha256:ABC", "image digest must be"),
    ],
)
def test_pin_digest_fails_closed_for_wrong_profile_or_digest(tmp_path, content, digest, error):
    profile = tmp_path / "allan-hermes-dev.yaml"
    profile.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        promotion.pin_digest(profile, digest)
