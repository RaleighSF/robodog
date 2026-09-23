#!/bin/bash
# Keep the Watch Dog patrol pipeline armed.
#
# Runs as a long-lived supervised loop rather than a systemd timer: on this
# systemd (245) a Type=oneshot timer fired but did not reliably reschedule, and
# a plain loop is far easier to reason about and verify. Idle cost is one local
# HTTP call per tick.
#
# Being a loop also makes power-on ORDER irrelevant - the dog can be switched on
# minutes or hours after the edge box and this will still arm the pipeline.
# The dashboard serves HTTPS with a self-signed cert; -k is safe here because
# this is loopback on the same box. Loopback is trusted by the operator login.
#
# Shared by the AGX (systemd) and the Thor (inside the watchdog container);
# each box overrides via environment:
#   WATCHDOG_DASH                  dashboard base URL (loopback)
#   WATCHDOG_SUPERVISOR_TOKEN_FILE auth.json holding the supervisor token, for
#                                  boxes where plain loopback is not trusted
#   ROBOT_CANDIDATES               robot addresses to probe, in order
DASH="${WATCHDOG_DASH:-https://127.0.0.1:8000}"
# The robot's address depends on which WiFi we are on. Probe the same candidate
# list the dashboard uses (see robot_host.py) and take the first that answers.
CANDIDATES="${ROBOT_CANDIDATES:-192.168.50.207 10.0.0.57 192.168.193.111 172.20.10.2 172.20.10.3 172.20.10.5 172.20.10.6 172.20.10.7 172.20.10.8 172.20.10.9}"   # Cradlepoint, home, ZeroTier, phone hotspot

# Dashboard calls. The token is re-read every call so a rotation is picked up.
dash() {
  if [ -n "${WATCHDOG_SUPERVISOR_TOKEN_FILE:-}" ]; then
    local tok
    tok=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('supervisor_token',''))" \
          "$WATCHDOG_SUPERVISOR_TOKEN_FILE" 2>/dev/null)
    curl -ksf -H "X-Watchdog-Supervisor: $tok" "$@"
  else
    curl -ksf "$@"
  fi
}
resolve_robot() {
  for h in $CANDIDATES; do
    if curl -sf -m3 "http://$h:5001/status" >/dev/null 2>&1; then echo "http://$h:5001"; return 0; fi
  done
  return 1
}
INTERVAL=60
log(){ echo "[autostart] $(date '+%H:%M:%S') $*"; }

log "supervisor started (interval ${INTERVAL}s)"
armed_note=0
while true; do
  if dash -m6 "$DASH/status" 2>/dev/null | grep -q '"is_running":true'; then
    armed_note=0
    sleep "$INTERVAL"; continue
  fi
  if ! dash -m6 "$DASH/status" >/dev/null 2>&1; then
    sleep "$INTERVAL"; continue
  fi
  ROBOT=$(resolve_robot) || { [ "$armed_note" -eq 0 ] && { log "no robot on any known address"; armed_note=1; }; sleep "$INTERVAL"; continue; }
  # Require a real WebRTC connection, not merely an open port.
  if ! curl -sf -m6 "$ROBOT/status" 2>/dev/null | grep -q '"connected":true'; then
    [ "$armed_note" -eq 0 ] && { log "waiting for robot"; armed_note=1; }
    sleep "$INTERVAL"; continue
  fi
  log "robot connected at $ROBOT - arming pipeline"
  dash -m20 -X POST "$DASH/switch_camera" -H 'Content-Type: application/json' -d '{"source":"go2_webrtc"}' >/dev/null 2>&1
  sleep 6
  dash -m20 -X POST "$DASH/start_detection" -H 'Content-Type: application/json' -d '{}' >/dev/null 2>&1
  sleep 8
  if dash -m6 "$DASH/status" 2>/dev/null | grep -q '"is_running":true'; then
    log "detection RUNNING"
    armed_note=0
  else
    log "arm did not take - retrying next tick"
  fi
  sleep "$INTERVAL"
done
