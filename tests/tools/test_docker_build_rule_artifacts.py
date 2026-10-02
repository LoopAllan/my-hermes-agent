"""Contracts for Docker build-time agent rule artifacts."""

from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts" / "build_rule_artifacts.py"
CANONICAL_RULES = REPO_ROOT / "docker" / "rules"
MARKER = "<!-- managed-by: docker/build_rule_artifacts.py -->"


def _run_generator(tmp_path: Path, rules: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    claude = tmp_path / "etc" / "claude-code" / "CLAUDE.md"
    codex = tmp_path / "etc" / "data" / "codex" / "AGENTS.md"
    for relative, content in rules.items():
        target = rules_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    result = subprocess.run(
        [str(GENERATOR), "--rules-dir", str(rules_dir), "--claude-output", str(claude), "--codex-output", str(codex)],
        cwd=REPO_ROOT,
        env={**os.environ, "PATH": f"{Path(sys.executable).parent}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        check=False,
    )
    return result, claude, codex


def test_generator_builds_deterministic_readonly_claude_and_codex_artifacts(tmp_path: Path) -> None:
    result, claude, codex = _run_generator(
        tmp_path,
        {"z-last.md": "# Last\n", "nested/a-first.md": "# First\n"},
    )

    assert result.returncode == 0, result.stderr
    assert claude.read_text(encoding="utf-8") == codex.read_text(encoding="utf-8")
    assert claude.read_text(encoding="utf-8").startswith(MARKER)
    assert "<!-- source: docker/rules/**/*.md -->" in claude.read_text(encoding="utf-8")
    assert claude.read_text(encoding="utf-8").index("nested/a-first.md") < claude.read_text(encoding="utf-8").index("z-last.md")
    assert claude.stat().st_mode & 0o777 == 0o444
    assert codex.stat().st_mode & 0o777 == 0o444


def test_generator_rejects_missing_or_empty_rule_sources(tmp_path: Path) -> None:
    result, claude, codex = _run_generator(tmp_path, {})

    assert result.returncode != 0
    assert "no Markdown rules" in result.stderr
    assert not claude.exists()
    assert not codex.exists()


def test_repository_ships_the_accepted_canonical_development_rules() -> None:
    rule_text = "\n".join(path.read_text(encoding="utf-8") for path in sorted(CANONICAL_RULES.rglob("*.md")))

    assert "GitHub Issue" in rule_text
    assert "GitHub Project" in rule_text
    assert "pull request" in rule_text.lower()
    assert "Traditional Chinese" in rule_text
    assert "Taiwan" in rule_text
    assert "skill" in rule_text.lower()
