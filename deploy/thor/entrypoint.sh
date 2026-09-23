#!/usr/bin/env bash
# Seed the writable config outside the git checkout on first run, so
# dashboard saves never dirty the repo and `git pull` stays clean.
set -euo pipefail
if [ -n "${WATCHDOG_CONFIG:-}" ] && [ ! -s "$WATCHDOG_CONFIG" ]; then
    mkdir -p "$(dirname "$WATCHDOG_CONFIG")"
    cp /app/config.yaml "$WATCHDOG_CONFIG"
    echo "[entrypoint] seeded $WATCHDOG_CONFIG from /app/config.yaml"
fi

# Self-signed TLS certificate on first run (kept in the state volume). Browsers
# warn once per device; the traffic is encrypted either way. Replace cert.pem /
# key.pem with a CA-issued pair to remove the warning.
if [ -n "${WATCHDOG_TLS_CERT:-}" ] && [ ! -s "$WATCHDOG_TLS_CERT" ]; then
    mkdir -p "$(dirname "$WATCHDOG_TLS_CERT")"
    san="DNS:localhost,DNS:${WATCHDOG_TLS_HOSTNAME:-watchdog},IP:127.0.0.1"
    for ip in ${WATCHDOG_TLS_IPS:-}; do san="$san,IP:$ip"; done
    ( umask 077
      openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 825 \
          -subj "/CN=${WATCHDOG_TLS_HOSTNAME:-watchdog}/O=NTT DATA Watch Dog" \
          -addext "subjectAltName=$san" \
          -keyout "$WATCHDOG_TLS_KEY" -out "$WATCHDOG_TLS_CERT" 2>/dev/null )
    echo "[entrypoint] generated self-signed TLS certificate ($san)"
fi
# Auto-arm: when the dog connects, switch to its camera and start detection
# (same script the AGX runs under systemd). Runs beside the app for the life of
# the container, so it stops automatically in Elastic-Vision mode. It talks to
# the dashboard over loopback with the supervisor token (loopback alone is not
# trusted here).
if [ "${WATCHDOG_AUTOARM:-0}" = 1 ]; then
    (
        while true; do
            bash /app/deploy/systemd/watchdog-autostart.sh 2>&1 | sed -u 's/^/[auto-arm] /'
            echo "[auto-arm] supervisor exited; restarting in 10s"
            sleep 10
        done
    ) &
fi

exec "$@"
