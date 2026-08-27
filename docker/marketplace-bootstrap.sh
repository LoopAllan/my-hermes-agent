#!/bin/sh
# shellcheck shell=sh
# Bootstrap an image-owned marketplace checkout only when config.yaml enables it.
# Credentials are read from the Vault-rendered env file and never logged.

set -eu
umask 077

fail() {
    printf '%s\n' "marketplace bootstrap: $1" >&2
    exit 1
}

marketplace_value() {
    python3 - "$1" <<'PY'
import os
import sys
from pathlib import Path

import yaml

field = sys.argv[1]
config_path = Path(os.environ["HERMES_HOME"]) / "config.yaml"
try:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
except (OSError, yaml.YAMLError) as exc:
    raise SystemExit(f"cannot read config.yaml: {exc}")
settings = (config.get("skills") or {}).get("marketplace") or {}
if not isinstance(settings, dict):
    raise SystemExit("skills.marketplace must be a mapping")
if field == "enabled":
    print("true" if settings.get("enabled") is True else "false")
    raise SystemExit
value = settings.get(field)
if not isinstance(value, str) or not value or "\n" in value or "\r" in value or "\x00" in value:
    raise SystemExit(f"skills.marketplace.{field} must be a nonempty single-line string")
print(os.path.expandvars(os.path.expanduser(value)) if field == "repo_dir" else value)
PY
}

marketplace_token() {
    python <<'PY'
import ast
import os
from pathlib import Path

path = os.environ.get("MARKETPLACE_VAULT_ENV_FILE")
if not path:
    raise SystemExit("Vault environment file is unavailable")
try:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
except OSError as exc:
    raise SystemExit(f"Vault environment file is unreadable: {exc}")
prefix = "MARKETPLACE_GIT_AUTH_TOKEN="
for line in lines:
    if line.startswith(prefix):
        raw_token = line[len(prefix):]
        if not raw_token.startswith('"'):
            break
        try:
            token = ast.literal_eval(raw_token)
        except (SyntaxError, ValueError):
            break
        if isinstance(token, str) and token and "\n" not in token and "\r" not in token:
            print(token)
            raise SystemExit
raise SystemExit("marketplace Git token is unavailable")
PY
}

require_config() {
    [ -n "$2" ] || fail "missing required configuration: $1"
}

require_config HERMES_HOME "${HERMES_HOME:-}"
[ -d "$HERMES_HOME" ] || fail "HERMES_HOME does not exist"

marketplace_enabled=$(marketplace_value enabled) || fail "invalid config.yaml"
[ "$marketplace_enabled" = "true" ] || exit 0
repository=$(marketplace_value repository) || fail "invalid config.yaml"
repo_dir=$(marketplace_value repo_dir) || fail "invalid config.yaml"
skills_path=$(marketplace_value skills_path) || fail "invalid config.yaml"
branch=$(marketplace_value branch) || fail "invalid config.yaml"
require_config MARKETPLACE_VAULT_ENV_FILE "${MARKETPLACE_VAULT_ENV_FILE:-}"

canonical_home=$(cd -P "$HERMES_HOME" && pwd -P) || fail "cannot resolve HERMES_HOME"
repository_parent=$(dirname "$repo_dir")
[ -d "$repository_parent" ] || fail "marketplace repository parent does not exist"
canonical_parent=$(cd -P "$repository_parent" && pwd -P) || fail "cannot resolve marketplace repository parent"
case "$canonical_parent" in
    "$canonical_home"|"$canonical_home"/*) ;;
    *) fail "marketplace repository directory must resolve below HERMES_HOME" ;;
esac
repository_dir="$canonical_parent/$(basename "$repo_dir")"

[ -r "$MARKETPLACE_VAULT_ENV_FILE" ] || fail "Vault environment file is not readable"
MARKETPLACE_GIT_AUTH_TOKEN=$(marketplace_token) || fail "marketplace Git token is unavailable"

credentials_file=$(mktemp "${TMPDIR:-/tmp}/hermes-marketplace-credentials.XXXXXX")
soul_tmp=
cleanup() {
    rm -f "${credentials_file:-}" "${soul_tmp:-}"
}
trap cleanup EXIT HUP INT TERM
chmod 0600 "$credentials_file"

# Git's credential-store format accepts a URL. Keep the token only in the
# mode-0600 temporary store, then remove it from this process environment.
credential_repository=${repository#https://}
credential_repository=${credential_repository#http://}
printf 'https://x-access-token:%s@%s\n' "$MARKETPLACE_GIT_AUTH_TOKEN" "$credential_repository" > "$credentials_file"
unset MARKETPLACE_GIT_AUTH_TOKEN

rm -rf "$repository_dir"
GIT_TERMINAL_PROMPT=0 git \
    -c "credential.helper=store --file=$credentials_file" \
    clone --depth 1 --single-branch --no-tags --branch "$branch" \
    "$repository" "$repository_dir"

skills_dir="$repository_dir/$skills_path"
[ -d "$skills_dir" ] || fail "configured skills directory is missing"

soul_source="$repository_dir/SOUL.md"
[ -f "$soul_source" ] && [ ! -L "$soul_source" ] || fail "root SOUL.md must be a regular non-symlink file"
soul_size=$(wc -c < "$soul_source")
[ "$soul_size" -gt 0 ] && [ "$soul_size" -le 20000 ] || fail "root SOUL.md must be nonempty and at most 20000 bytes"

soul_tmp=$(mktemp "$HERMES_HOME/.SOUL.md.XXXXXX")
chmod 0600 "$soul_tmp"
cat "$soul_source" > "$soul_tmp"
mv -f "$soul_tmp" "$HERMES_HOME/SOUL.md"
soul_tmp=
