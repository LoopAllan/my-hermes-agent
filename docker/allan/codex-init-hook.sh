#!/bin/sh
# Allan-derived image hook: preserve the immutable Codex rules file while
# reconciling only first-level mutable Codex runtime state before services run.
set -eu

CODEX_HOME=/etc/data/codex

if [ -d "$CODEX_HOME" ]; then
    find "$CODEX_HOME" -mindepth 1 -maxdepth 1 ! -name AGENTS.md ! -type l -exec chown -h hermes:hermes {} + 2>/dev/null || \
        echo "[allan-codex-init] Warning: chown Codex runtime state failed (rootless container?) — continuing"
    if [ -f "$CODEX_HOME/AGENTS.md" ]; then
        chown root:root "$CODEX_HOME/AGENTS.md" 2>/dev/null || true
        chmod 0444 "$CODEX_HOME/AGENTS.md" 2>/dev/null || true
        chown root:hermes "$CODEX_HOME" 2>/dev/null || true
        chmod 1770 "$CODEX_HOME" 2>/dev/null || true
    fi
fi
