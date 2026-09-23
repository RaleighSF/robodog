# Watch Dog's robot link on the dog's Orin (firmware 1.1.15+).
# Built FROM Azimuth's edge image because it already carries the proven stack
# for this robot: ROS 2 Humble + CycloneDDS, unitree_api/unitree_go messages,
# and unitree_webrtc_connect 2.2.0 (per-device AES key) for video. Only one of
# the two runs at a time (systemd Conflicts= in both units).
FROM azimuth-edge:dev
COPY go2_service.py /opt/watchdog/go2_service.py
COPY entrypoint.sh /opt/watchdog/entrypoint.sh
RUN chmod +x /opt/watchdog/entrypoint.sh
WORKDIR /opt/watchdog
ENTRYPOINT ["/opt/watchdog/entrypoint.sh"]
