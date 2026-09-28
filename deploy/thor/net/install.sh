#!/bin/bash
# One-time network hardening for the Thor. Run with sudo:
#   ssh -t thor 'sudo bash ~/watch_dog/deploy/thor/net/install.sh'
# 1. WiFi watchdog service (see wifi-watchdog.sh).
# 2. Wired profile also carries the Cradlepoint address 192.168.50.210, so a
#    cable into the Cradlepoint works with no changes (home 192.168.1.234 kept).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 1; }

install -m 755 "$HERE/wifi-watchdog.sh" /usr/local/sbin/wifi-watchdog.sh
install -m 644 "$HERE/wifi-watchdog.service" /etc/systemd/system/wifi-watchdog.service
systemctl daemon-reload
systemctl enable --now wifi-watchdog.service
echo "wifi-watchdog: $(systemctl is-enabled wifi-watchdog) / $(systemctl is-active wifi-watchdog)"

WIRED="Wired connection 1"
if nmcli -g ipv4.addresses con show "$WIRED" | grep -q "192.168.50.210"; then
  echo "wired: 192.168.50.210 already present"
else
  nmcli con modify "$WIRED" +ipv4.addresses 192.168.50.210/24
  echo "wired: added 192.168.50.210/24 (applies on next link-up; re-applying now)"
  nmcli device reapply enP2p1s0 >/dev/null 2>&1 || true
fi
echo "wired addresses: $(nmcli -g ipv4.addresses con show "$WIRED")"
