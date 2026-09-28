#!/bin/bash
# Thor WiFi watchdog. The Realtek RTL8852CE (rtl8852ce) can stall silently:
# NetworkManager still reports "connected" with a lease, but no traffic passes,
# and nothing recovers it (seen 2026-09-28: ~40 min dark until a reboot).
#
# Every INTERVAL s: the link is healthy if, over the WiFi interface itself,
# the default gateway OR a robot address on the same subnet answers a ping.
# After FAILS consecutive misses: reconnect the WiFi (NetworkManager picks the
# highest-priority visible profile: Cradlepoint first). If it is still dark
# after that: reload the driver - at most once per DRIVER_BACKOFF s.
#
# Note: this catches a DEAD link. The failure actually seen on 2026-09-28 was
# different - the card stopped answering broadcast ARP (new devices could not
# reach the Thor; existing peers and the gateway still could), which pings from
# the Thor cannot detect. That one is fixed at the source by turning driver
# power saving off (install.sh, /etc/modprobe.d/rtl8852ce-watchdog.conf).
IFACE="${IFACE:-wlP1p1s0}"
DRIVER="${DRIVER:-rtl8852ce}"
INTERVAL="${INTERVAL:-30}"
FAILS="${FAILS:-3}"
GRACE="${GRACE:-60}"                   # after a reconnect/reload, let it settle
DRIVER_BACKOFF="${DRIVER_BACKOFF:-900}"
ROBOTS="${ROBOTS:-192.168.50.207 10.0.0.57}"

log(){ echo "[wifi-watchdog] $*"; }
alive() {
  local gw ip4
  ip4="$(ip -4 -o addr show dev "$IFACE" 2>/dev/null | awk '{print $4}' | head -1)"
  [ -n "$ip4" ] || return 2                                  # no address: not associated
  gw="$(ip -4 route show default dev "$IFACE" 2>/dev/null | awk '{print $3}' | head -1)"
  for h in $gw $ROBOTS; do
    ping -I "$IFACE" -c1 -W2 "$h" >/dev/null 2>&1 && return 0
  done
  return 1
}

misses=0; reconnects=0; last_reload=0
log "watching $IFACE (driver $DRIVER), ${INTERVAL}s interval, act after $FAILS misses"
while true; do
  if alive; then
    [ "$misses" -gt 0 ] && log "link healthy again after $misses miss(es)"
    misses=0; reconnects=0
  else
    rc=$?
    misses=$((misses + 1))
    [ "$rc" -eq 2 ] && why="no IPv4 on $IFACE" || why="no reply from gateway/robot"
    log "miss $misses/$FAILS ($why)"
    if [ "$misses" -ge "$FAILS" ]; then
      now=$(date +%s)
      if [ "$reconnects" -lt 1 ] || [ $((now - last_reload)) -lt "$DRIVER_BACKOFF" ]; then
        log "reconnecting $IFACE"
        nmcli device disconnect "$IFACE" >/dev/null 2>&1
        sleep 3
        nmcli device connect "$IFACE" 2>&1 | sed 's/^/[wifi-watchdog] nmcli: /'
        reconnects=$((reconnects + 1))
      else
        log "still dark after reconnect - reloading driver $DRIVER"
        modprobe -r "$DRIVER" && sleep 2 && modprobe "$DRIVER"
        last_reload=$now; reconnects=0
      fi
      misses=0
      sleep "$GRACE"
      continue
    fi
  fi
  sleep "$INTERVAL"
done
