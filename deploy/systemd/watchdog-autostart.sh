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
DASH="http://127.0.0.1:8000"
# The robot's address depends on which WiFi we are on. Probe the same candidate
# list the dashboard uses (see robot_host.py) and take the first that answers.
CANDIDATES="192.168.50.207 10.0.0.57 192.168.193.111"   # Cradlepoint, home, ZeroTier
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
  if curl -sf -m6 "$DASH/status" 2>/dev/null | grep -q '"is_running":true'; then
    armed_note=0
    sleep "$INTERVAL"; continue
  fi
  if ! curl -sf -m6 "$DASH/status" >/dev/null 2>&1; then
    sleep "$INTERVAL"; continue
  fi
  ROBOT=$(resolve_robot) || { [ "$armed_note" -eq 0 ] && { log "no robot on any known address"; armed_note=1; }; sleep "$INTERVAL"; continue; }
  # Require a real WebRTC connection, not merely an open port.
  if ! curl -sf -m6 "$ROBOT/status" 2>/dev/null | grep -q '"connected":true'; then
    [ "$armed_note" -eq 0 ] && { log "waiting for robot"; armed_note=1; }
    sleep "$INTERVAL"; continue
  fi
  log "robot connected at $ROBOT - arming pipeline"
  curl -sf -m20 -X POST "$DASH/switch_camera" -H 'Content-Type: application/json' -d '{"source":"go2_webrtc"}' >/dev/null 2>&1
  sleep 6
  curl -sf -m20 -X POST "$DASH/start_detection" -H 'Content-Type: application/json' -d '{}' >/dev/null 2>&1
  sleep 8
  if curl -sf -m6 "$DASH/status" 2>/dev/null | grep -q '"is_running":true'; then
    log "detection RUNNING"
    armed_note=0
  else
    log "arm did not take - retrying next tick"
  fi
  sleep "$INTERVAL"
done
