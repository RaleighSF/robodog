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

# 3. Realtek RTL8852CE driver power saving OFF. With the defaults
#    (rtw_lps_mode=4, rtw_ips_mode=5) the card stopped answering broadcast ARP
#    on 2026-09-28: hosts already talking to the Thor kept working, but any NEW
#    device (a demo laptop!) could not reach it. NetworkManager's powersave
#    setting does not control these driver-level modes. Takes effect when the
#    driver reloads (below: WiFi drops for ~10-20 s; the dog's video reconnects).
MODCONF=/etc/modprobe.d/rtl8852ce-watchdog.conf
echo "options rtl8852ce rtw_lps_mode=0 rtw_ips_mode=0" > "$MODCONF"
echo "driver: $(cat "$MODCONF")"
if [ "$(cat /sys/module/rtl8852ce/parameters/rtw_lps_mode)" != "0" ]; then
  echo "driver: reloading rtl8852ce to apply (WiFi drops briefly)"
  modprobe -r rtl8852ce && sleep 2 && modprobe rtl8852ce
  sleep 15
fi
echo "driver now: lps=$(cat /sys/module/rtl8852ce/parameters/rtw_lps_mode) ips=$(cat /sys/module/rtl8852ce/parameters/rtw_ips_mode)"

WIRED="Wired connection 1"
if nmcli -g ipv4.addresses con show "$WIRED" | grep -q "192.168.50.210"; then
  echo "wired: 192.168.50.210 already present"
else
  nmcli con modify "$WIRED" +ipv4.addresses 192.168.50.210/24
  echo "wired: added 192.168.50.210/24 (applies on next link-up; re-applying now)"
  nmcli device reapply enP2p1s0 >/dev/null 2>&1 || true
fi
echo "wired addresses: $(nmcli -g ipv4.addresses con show "$WIRED")"
