# Watch Dog's robot link on the dog's Orin (firmware 1.1.15+).
# Built FROM Azimuth's edge image because it already carries the proven stack
# for this robot: ROS 2 Humble + CycloneDDS, unitree_api/unitree_go messages,
# and unitree_webrtc_connect 2.2.0 (per-device AES key) for video. Only one of
# the two runs at a time (systemd Conflicts= in both units).
# Pinned: a Watch Dog-owned tag of the exact azimuth-edge image this was tested
# on (tagged on the Orin 2026-09-23). An Azimuth rebuild of azimuth-edge:dev can
# no longer silently change our base; re-tag deliberately to upgrade.
FROM watchdog-go2-base:2026-09-23
COPY go2_service.py /opt/watchdog/go2_service.py
COPY entrypoint.sh /opt/watchdog/entrypoint.sh
RUN chmod +x /opt/watchdog/entrypoint.sh
WORKDIR /opt/watchdog
ENTRYPOINT ["/opt/watchdog/entrypoint.sh"]
