"""Contracts for build-time development-rule artifacts."""

from scripts.build_rule_artifacts import build_artifacts


def test_build_artifacts_can_emit_only_codex_rules(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "base.md").write_text("Keep runtime rules immutable.\n", encoding="utf-8")
    codex_output = tmp_path / "codex" / "AGENTS.md"

    build_artifacts(rules_dir=rules, claude_output=None, codex_output=codex_output)

    assert codex_output.read_text(encoding="utf-8").endswith("Keep runtime rules immutable.\n")
    assert codex_output.stat().st_mode & 0o777 == 0o444
