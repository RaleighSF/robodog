#!/usr/bin/env bash
# Seed the writable config outside the git checkout on first run, so
# dashboard saves never dirty the repo and `git pull` stays clean.
set -euo pipefail
if [ -n "${WATCHDOG_CONFIG:-}" ] && [ ! -s "$WATCHDOG_CONFIG" ]; then
    mkdir -p "$(dirname "$WATCHDOG_CONFIG")"
    cp /app/config.yaml "$WATCHDOG_CONFIG"
    echo "[entrypoint] seeded $WATCHDOG_CONFIG from /app/config.yaml"
fi
exec "$@"
