#!/bin/sh
# shellcheck shell=sh
# Thin image entrypoint; marketplace behavior lives in focused Python modules.

set -eu
umask 077
exec /opt/hermes/.venv/bin/python -m gateway.marketplace_bootstrap "$@"
