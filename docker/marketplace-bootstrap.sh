#!/bin/sh
# shellcheck shell=sh
# Bootstrap an image-owned marketplace checkout only when explicitly enabled.
# Credentials are read from the Vault-rendered env file and never logged.

if [ "${MARKETPLACE_BOOTSTRAP_ENABLED:-}" != "true" ]; then
    exit 0
fi

set -eu
umask 077

fail() {
    printf '%s\n' "marketplace bootstrap: $1" >&2
    exit 1
}

require_config() {
    [ -n "$2" ] || fail "missing required configuration: $1"
}

require_config MARKETPLACE_VAULT_ENV_FILE "${MARKETPLACE_VAULT_ENV_FILE:-}"
require_config MARKETPLACE_REPOSITORY "${MARKETPLACE_REPOSITORY:-}"
require_config MARKETPLACE_REF "${MARKETPLACE_REF:-}"
require_config MARKETPLACE_MOUNT_PATH "${MARKETPLACE_MOUNT_PATH:-}"
require_config MARKETPLACE_SKILLS_PATH "${MARKETPLACE_SKILLS_PATH:-}"
require_config HERMES_HOME "${HERMES_HOME:-}"

[ -d "$HERMES_HOME" ] || fail "HERMES_HOME does not exist"
[ -d "$MARKETPLACE_MOUNT_PATH" ] || fail "marketplace mount path does not exist"
canonical_home=$(cd -P "$HERMES_HOME" && pwd -P) || fail "cannot resolve HERMES_HOME"
canonical_mount=$(cd -P "$MARKETPLACE_MOUNT_PATH" && pwd -P) || fail "cannot resolve marketplace mount path"
case "$canonical_mount" in
    "$canonical_home"/*) ;;
    *) fail "marketplace mount path must resolve below HERMES_HOME" ;;
esac

[ -r "$MARKETPLACE_VAULT_ENV_FILE" ] || fail "Vault environment file is not readable"
set -a
. "$MARKETPLACE_VAULT_ENV_FILE"
set +a
[ -n "${MARKETPLACE_GIT_AUTH_TOKEN:-}" ] || fail "marketplace Git token is unavailable"

credentials_file=$(mktemp "${TMPDIR:-/tmp}/hermes-marketplace-credentials.XXXXXX")
soul_tmp=
cleanup() {
    rm -f "${credentials_file:-}" "${soul_tmp:-}"
}
trap cleanup EXIT HUP INT TERM
chmod 0600 "$credentials_file"

# Git's credential-store format accepts a URL. Keep the token only in the
# mode-0600 temporary store, then remove it from this process environment.
credential_repository=${MARKETPLACE_REPOSITORY#https://}
credential_repository=${credential_repository#http://}
printf 'https://x-access-token:%s@%s\n' "$MARKETPLACE_GIT_AUTH_TOKEN" "$credential_repository" > "$credentials_file"
unset MARKETPLACE_GIT_AUTH_TOKEN

repository_dir="$canonical_mount/repository"
rm -rf "$repository_dir"
GIT_TERMINAL_PROMPT=0 git \
    -c "credential.helper=store --file=$credentials_file" \
    clone --depth 1 --single-branch --no-tags --branch "$MARKETPLACE_REF" \
    "$MARKETPLACE_REPOSITORY" "$repository_dir"

skills_dir="$repository_dir/$MARKETPLACE_SKILLS_PATH"
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
