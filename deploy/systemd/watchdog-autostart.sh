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
ROBOT="http://10.0.0.57:5001"
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
  # Require a real WebRTC connection, not merely an open port.
  if ! curl -sf -m6 "$ROBOT/status" 2>/dev/null | grep -q '"connected":true'; then
    [ "$armed_note" -eq 0 ] && { log "waiting for robot"; armed_note=1; }
    sleep "$INTERVAL"; continue
  fi
  log "robot connected - arming pipeline"
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
