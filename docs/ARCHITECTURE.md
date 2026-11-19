# Watch Dog architecture: robot link, safety model, pipelines

Current as of 2026-09-23 (main `d075d02`). The safety design was reviewed over
9 rounds by Astra (Codex) and ended in ACCEPT for a supervised, Thor-only demo.

## 1. Robot link (Orin, `go2_service.py`)

Firmware 1.1.15 moved the Go2's command interface to **DDS**. The old
WebRTC-command service no longer connects. The link now copies Azimuth's
proven transport:

- **Commands and telemetry over DDS** (rclpy + CycloneDDS, ROS 2 Humble), with
  lease id 0:
  - requests on `/api/sport/request`;
  - replies on `/api/sport/response`, matched by `header.identity.id`;
  - telemetry from `/lf/lowstate` and `/lf/sportmodestate`;
  - mode changes via `motion_switcher` (CheckMode 1001 / SelectMode 1002).
- **Sport API ids**: StopMove 1003, StandDown 1005, RecoveryStand 1006,
  Move 1008, Sit 1009, RiseSit 1010, Hello (shake) 1016.
- **Video** comes over a video-only WebRTC connection (`unitree_webrtc_connect`
  2.2.0 with the per-device AES key). The Orin re-encodes it as MJPEG, and the
  connection reconnects after 10 s without frames.
- The DDS pieces come from the shared **go2dds** library:
  - `DDSCore`: an rclpy context/executor thread, request correlation, and
    `Pending` objects;
  - `RestVerifier`: Azimuth's `settle_still`;
  - the topic and API tables;
  - motion floors (0.22 m/s forward, 0.45 rad/s turn; reverse is capped at
    -0.15 m/s).
- The image is built FROM a pinned image ID of Azimuth's edge build.
  `Conflicts=azimuth-edge.service` keeps the two from running together.

### HTTP contract (HTTPS :5001, demo-CA certificate)

| Endpoint | Auth | Notes |
| --- | --- | --- |
| `GET /status`, `/battery`, `/video_feed` | public | read-only |
| `POST /move` | token + session + seq + permit | see Driving |
| `POST /command` (stand/crouch/sit/shake), `/motion_mode` | token | goes through a verified stop first |
| `POST /stop` | token, or anonymous as an E-stop | anonymous stops coalesce onto the outstanding one |

- The token is `Authorization: Bearer <GO2_SERVICE_TOKEN>`: at least 32
  ASCII characters with no whitespace. With no valid token configured, every
  command endpoint refuses (fail closed).
- The server speaks HTTP/1.1, so the Thor's pooled connections stay open.
  Measured: 20 calls over 1 TLS connection, p50 45 ms.

### Stops: "done" means verified at rest

A stop counts as confirmed only when **both** of these hold:

- the robot replied to StopMove with **any** code (a lying dog answers -1);
- **fresh** telemetry shows the body still. Planar speed must stay below
  0.03 m/s and yaw rate below 0.05 rad/s, on at least 4 distinct samples
  spanning 0.3 s. The verdict is current: motion or stale telemetry resets it.

Stops are numbered, and each one is confirmed only for its own number.
Unconfirmed stops are retried every 2.5 s.

Posture commands (stand / crouch / sit / shake):

- A command first waits for its own verified stop.
- It is published only if no newer stop and no operator stop arrived since it
  was admitted. An E-stop at any moment cancels a pending posture change.
- Stand maps to RiseSit when the robot reads low, otherwise to RecoveryStand.

### Driving: sessions, lease, permits

1. **Sessions**. Each D-pad press is one session: a random id generated in the
   browser, with an increasing `seq`.
   - Releasing sends a named stop that **retires** the session. Retired ids
     are kept for the process lifetime.
   - One controller at a time: another session gets `BUSY` while a drive is
     live.
2. **Lease (deadman)**. Every Move authorizes 0.4 s of motion. The browser
   renews every 150 ms. If renewals stop, the Orin stops the dog and retires
   the press.
   - This is **deliberate fail-stop**. Continuous renewal is not guaranteed on
     a stalled network; the operator presses again.
3. **Robot-issued permits** (freshness).
   - A Move moves the dog only if it carries a permit the Orin issued for that
     press less than **0.5 s** ago, on the Orin's own clock.
   - Only the current permit and the one before it are valid.
   - The first Move of a press only fetches a permit (`409 PERMIT`, no motion)
     and is resent at once. Every accepted Move returns the next permit.
   - Retiring or stopping a press voids its permits.
   - So a Move delayed anywhere (browser, Thor, network) can never *start*
     motion late.
4. **Released-press retirement is retried**. The Thor remembers released
   sessions and re-sends them (a `retire:[...]` list, or a retire-only stop
   from the backup deadman) until the Orin confirms.
   - The Orin retires listed sessions even if it never saw them.
   - A retire-only stop never stops a different, live press. The retirement
     and the stop it needs happen under one lock.
5. **Thor-side deadline and backpressure**.
   - The move proxy answers within 0.3 s.
   - It has 2 sender slots. When both are busy, a Move is refused, never
     queued (no backlog).
   - Each Move re-checks its deadline immediately before sending, so an
     expired Move is never sent.

**Accepted residuals** (documented in code):

- After the last fresh permit, the commanded-motion window is at most
  0.5 + 0.4 s. That is about 0.29 m at the 0.32 m/s combined speed cap, plus
  scheduling, stop delivery and braking. It is **not** a stopping-distance
  guarantee.
- The 2 sender slots can be held by stalled requests until their socket
  timeouts fire.
- A permit may authorize one more higher-seq Move while it is the "previous"
  permit.

### E-stop (dashboard)

- The E-stop sends `all: true` with the page's own press.
- The D-pad stays **latched** until the Orin confirms the stop at rest.
  Unconfirmed attempts retry; pressing again joins the attempt in flight.
- An anonymous `/stop` from any other client is still honoured. It always
  counts as an operator stop, and at most 4 of them wait on a server thread.

## 2. Thor pipeline (`web_app.py`, `camera.py`)

- **Capture**:
  - one capture thread per generation (a restart retires the old thread);
  - frames carry a sequence number and a monotonic receive time;
  - a Condition wakes the consumers;
  - `camera.stop()` clears the frame timestamp, so a stopped feed never looks
    fresh.
- **Detection** is new-frame driven, through a single latest-frame slot, so it
  never lags the camera.
- **Gesture**:
  - It runs on its own worker from a latest-frame slot. The capture timestamp
    travels with each frame from the feeder, through the queue, to the
    decision.
  - Frames older than 0.5 s are refused.
  - After inference, the worker re-checks that gesture is still armed and that
    the frame is still fresh, then sends `shake`.
  - Arming is a 90 s lease renewed by the open Gesture tab. It disarms on
    `pagehide` or when the operator switches to Observe.
  - A hand must fill at least 2.5 % of the frame and win a 2-of-4 vote.
- **Narration** posts frames to Cosmos (`http://vllm:8000/v1`, OpenAI API).
  One frame takes about 2.4 s; the narrator runs every 8 s.
- **Robot HTTP** goes through `robot_host`. Discovery is verified against the
  pinned demo CA (`WATCHDOG_ROBOT_CA=/state/tls/ca.pem`). There are two pooled
  sessions: a public one with no token, and a control one with the token. The
  drive path uses the cached address and never probes inside a Move's deadline.
- **Auto-arm supervisor** (`watchdog-autostart.sh`, inside the container):
  - it probes the robot over HTTPS with `--cacert` and requires an explicit
    `has_video: true`;
  - it arms go2 video and detection, and reports healthy only on
    `video_fresh: true`;
  - it re-arms after two stale checks;
  - it authenticates to the dashboard with a loopback-only supervisor token.

## 3. Deployment safety (Orin `build.sh` + `remote-deploy.sh`)

1. The go2dds revision pinned in `GO2DDS_REV` is exported with `git archive`.
   Uncommitted edits never ship.
2. Staging goes to a private remote directory. The whole deploy is serialized
   by `flock`.
3. The new image is built. Its `--preflight` runs under the unit's real
   `EnvironmentFile` (via `systemd-run`) with the real TLS mount: it checks the
   token rules, the AES key, the certificate/key pair, and certificate expiry.
4. Rollback point: the running container's image plus a sudo backup of the
   unit. Absence is established only by successful empty listings; any
   unknown state aborts.
5. The exact image ID is promoted and the service restarted. The health gate
   (demo CA, `connected` + `has_video`, 90 s) must pass, or the image **and**
   unit are rolled back.
6. This was drilled: a deliberately broken build passed preflight, failed
   health, and rolled back healthy.
