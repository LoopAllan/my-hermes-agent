#!/bin/sh
# shellcheck shell=sh
# Thin image entrypoint; marketplace behavior lives in focused Python modules.

set -eu
umask 077
exec python3 -m gateway.marketplace_bootstrap "$@"
