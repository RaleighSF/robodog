# Watch Dog's robot link on the dog's Orin (firmware 1.1.15+).
# Built FROM Azimuth's edge image because it already carries the proven stack
# for this robot: ROS 2 Humble + CycloneDDS, unitree_api/unitree_go messages,
# and unitree_webrtc_connect 2.2.0 (per-device AES key) for video. Only one of
# the two runs at a time (systemd Conflicts= in both units).
# Pinned by immutable image ID (the tested azimuth-edge build; also tagged
# watchdog-go2-base:2026-09-23 on the Orin). A different base cannot slip in.
FROM sha256:49324fa00c15de6e7b2ffd6060d43ce87a18d524ef290f48efa58490b0b2e318
COPY go2_service.py /opt/watchdog/go2_service.py
# Shared Go2 DDS library (same code as Azimuth), staged by deploy/orin/build.sh.
COPY go2dds /opt/watchdog/go2dds
COPY entrypoint.sh /opt/watchdog/entrypoint.sh
RUN chmod +x /opt/watchdog/entrypoint.sh
WORKDIR /opt/watchdog
ENTRYPOINT ["/opt/watchdog/entrypoint.sh"]
