#!/bin/sh
# shellcheck shell=sh
# Thin image entrypoint; marketplace behavior lives in focused Python modules.
# Runs from the s6 cont-init hook and, unchanged, as a direct-bootstrap.d hook
# when the container is not PID 1, so it owns the drop to the runtime user
# (skipped when already non-root, like stage2-hook's as_hermes).

set -eu
umask 077
if [ "$(id -u)" = 0 ]; then
    exec s6-setuidgid hermes /bin/sh "$0" "$@"
fi
if [ -x /opt/hermes/.venv/bin/python ]; then
    exec /opt/hermes/.venv/bin/python -m gateway.marketplace_bootstrap "$@"
fi

# Source-checkout tests do not have the image's baked venv. The production
# path above remains mandatory whenever the image layout is present.
exec python3 -m gateway.marketplace_bootstrap "$@"
