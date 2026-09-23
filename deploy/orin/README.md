# Watch Dog robot link on the dog's Orin

Firmware 1.1.15 stopped the old WebRTC `go2_service` from connecting. This
replacement copies the transport Azimuth proved on the same robot:

- **Commands and telemetry go over DDS** (`/api/sport/request`,
  `/lf/lowstate`, `/lf/sportmodestate`) with lease 0.
- **Video goes over a video-only WebRTC link** that uses the per-device AES key.

The HTTP contract on `:5001` is unchanged, so the dashboards (AGX and Thor)
and the auto-arm supervisor need no changes.

Only one of the Watch Dog link and Azimuth's `azimuth-edge` runs at a time.
Both systemd units declare `Conflicts=`, so starting one stops the other.

```bash
# on the Orin (unitree@<orin>), from a copy of this folder plus ../../go2_service.py
docker build -t watchdog-go2:latest .
sudo install -m 600 /dev/null /etc/go2_service.env      # then put GO2_AES_KEY=<key> in it
sudo install -m 644 go2_service.service /etc/systemd/system/go2_service.service
sudo systemctl daemon-reload && sudo systemctl enable --now go2_service
```

Command mapping:

| Dashboard command | Sport API call |
|---|---|
| stand | RecoveryStand 1006, the balance stance the robot can walk from. From sitting it sends RiseSit 1010 instead. |
| crouch | StandDown 1005 |
| sit | Sit 1009 |
| shake | Hello 1016 |
| move | Move 1008, clamped to vx -0.15..0.25, vy ±0.2, vyaw ±0.5 |
| stop | StopMove 1003, always sent |

The image is built FROM `azimuth-edge:dev`. The Azimuth lockdown script
deletes that image, so rebuild both after a restore.
