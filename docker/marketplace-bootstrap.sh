#!/bin/sh
# shellcheck shell=sh
# Thin image entrypoint; marketplace behavior lives in focused Python modules.

set -eu
umask 077
if [ -x /opt/hermes/.venv/bin/python ]; then
    exec /opt/hermes/.venv/bin/python -m gateway.marketplace_bootstrap "$@"
fi

# Source-checkout tests do not have the image's baked venv. The production
# path above remains mandatory whenever the image layout is present.
exec python3 -m gateway.marketplace_bootstrap "$@"
