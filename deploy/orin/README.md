# Watch Dog robot link on the dog's Orin

Firmware 1.1.15 stopped the old WebRTC `go2_service` from connecting. This
replacement copies the transport Azimuth proved on the same robot:

- **Commands and telemetry go over DDS** (`/api/sport/request`,
  `/lf/lowstate`, `/lf/sportmodestate`) with lease 0.
- **Video goes over a video-only WebRTC link** that uses the per-device AES key.

The DDS layer comes from the shared **go2dds** library (`../go2dds`, used by
Azimuth too). `build.sh` ships the revision pinned in `GO2DDS_REV`, exported
with `git archive`, so uncommitted edits in the go2dds checkout never ship.

**HTTP contract on `:5001` (HTTPS only):**
- The server certificate is issued by the Watch Dog demo CA. The Thor verifies
  it against `/state/tls/ca.pem`.
- `status`, `battery` and `video_feed` are public reads.
- Every other endpoint needs `Authorization: Bearer <GO2_SERVICE_TOKEN>`,
  which only the Thor holds.
- An unauthenticated `/stop` is still honoured as an E-stop.
- `/move` requires a drive `session` and `seq` from the browser. Older
  dashboards (the AGX's) are refused and are view-only.

Only one of the Watch Dog link and Azimuth's `azimuth-edge` runs at a time.
Both systemd units declare `Conflicts=`, so starting one stops the other.

**Prerequisites on the Orin (one time, never committed):**

```bash
sudo install -m 600 /dev/null /etc/go2_service.env
# add: GO2_AES_KEY=<per-device key>  and  GO2_SERVICE_TOKEN=<>=32 random chars, no spaces>
sudo install -d -m 755 /etc/watchdog-go2/tls
# cert.pem (0644) + key.pem (0600): issued on the Mac by ~/.watchdog-ca
# with SANs for every Orin address (10.0.0.57, 192.168.50.207, 192.168.123.18, 127.0.0.1).
```

Put the same token in the Thor's state volume at `/state/robot_token`, and the
demo CA at `/state/tls/ca.pem`.

**Deploy (from the Mac):**

```bash
SSHPASS=<orin password> deploy/orin/build.sh unitree@10.0.0.57
```

`build.sh` builds a candidate image and runs `go2_service.py --preflight`
inside it, with the unit's real environment (via `systemd-run -p
EnvironmentFile=`) and the TLS mount. The preflight applies the service's own
token rules, loads the certificate/key pair (so a mismatch or a corrupt file
fails) and rejects a certificate expiring within a day. The running service is
replaced only if the preflight passes.

Command mapping:

| Dashboard command | Sport API call |
|---|---|
| stand | RecoveryStand 1006, the balance stance the robot can walk from. From sitting it sends RiseSit 1010 instead. |
| crouch | StandDown 1005 |
| sit | Sit 1009 |
| shake | Hello 1016 |
| move | Move 1008, clamped to vx -0.15..0.25, vy ±0.2, vyaw ±0.5 |
| stop | StopMove 1003, always sent |

The image is built FROM a pinned image ID of Azimuth's edge build, which is
also tagged `watchdog-go2-base:2026-09-23` on the Orin. If the Azimuth lockdown
script removes it, re-tag that base (or rebuild it and update the pinned
Dockerfile `FROM`) before running `build.sh`.
