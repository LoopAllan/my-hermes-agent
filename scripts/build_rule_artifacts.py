#!/usr/bin/env python3
"""Build immutable instruction artifacts from canonical rules."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys
import tempfile
from typing import Iterable


MANAGED_MARKER = "<!-- managed-by: docker/build_rule_artifacts.py -->"
SOURCE_MARKER = "<!-- source: docker/rules/**/*.md -->"


class RuleBuildError(RuntimeError):
    """Raised when canonical rule artifacts cannot be built."""


def read_sources(rules_dir: Path) -> list[tuple[Path, bytes]]:
    if not rules_dir.is_dir():
        raise RuleBuildError(f"rules directory does not exist: {rules_dir}")

    sources = [
        (path.relative_to(rules_dir), path.read_bytes())
        for path in sorted(rules_dir.rglob("*.md"), key=lambda candidate: candidate.as_posix())
        if path.is_file() and not path.is_symlink()
    ]
    if not sources:
        raise RuleBuildError(f"no Markdown rules found under: {rules_dir}")
    return sources


def source_digest(sources: Iterable[tuple[Path, bytes]]) -> str:
    digest = hashlib.sha256()
    for relative, content in sources:
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def aggregate(sources: list[tuple[Path, bytes]]) -> str:
    digest = source_digest(sources)
    sections = [
        MANAGED_MARKER,
        SOURCE_MARKER,
        f"<!-- source-digest: sha256:{digest} -->",
        "<!-- generated during Docker image build; do not edit -->",
        "",
        "# Shared Development Rules",
    ]
    for relative, raw_content in sources:
        sections.extend(["", f"## Source: `{relative.as_posix()}`", "", raw_content.decode("utf-8").strip()])
    return "\n".join(sections).rstrip() + "\n"


def write_readonly(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as temporary:
        temporary.write(content)
        temporary.flush()
        temporary_path = Path(temporary.name)
    temporary_path.chmod(0o444)
    temporary_path.replace(path)
    path.chmod(0o444)


def build_artifacts(
    *, rules_dir: Path, claude_output: Path | None, codex_output: Path | None,
) -> None:
    content = aggregate(read_sources(rules_dir))
    if claude_output is not None:
        write_readonly(claude_output, content)
    if codex_output is not None:
        write_readonly(codex_output, content)


def parse_args() -> argparse.Namespace:
    repository_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules-dir", type=Path, default=repository_root / "docker" / "rules")
    parser.add_argument("--claude-output", type=Path)
    parser.add_argument("--codex-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.claude_output is None and args.codex_output is None:
        print("[rule-build] ERROR: choose at least one output", file=sys.stderr)
        return 1
    try:
        build_artifacts(
            rules_dir=args.rules_dir,
            claude_output=args.claude_output,
            codex_output=args.codex_output,
        )
    except (OSError, UnicodeError, RuleBuildError) as exc:
        print(f"[rule-build] ERROR: {exc}", file=sys.stderr)
        return 1
    if args.claude_output is not None:
        print(f"[rule-build] installed {args.claude_output}")
    if args.codex_output is not None:
        print(f"[rule-build] installed {args.codex_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
