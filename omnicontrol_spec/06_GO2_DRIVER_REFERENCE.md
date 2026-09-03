# Appendix E — Unitree Go2 Driver Reference

> Part of the OmniControl Platform Design Specification.
> This appendix is the accumulated field knowledge from an 11-month Go2 deployment
> (`watch_dog`, NTT DATA, Snowflake Summit 2026). **Everything here was learned the hard
> way, often by dropping a 15 kg robot on a concrete floor.** Treat every warning as
> load-bearing.
>
> Citations are `file:line` into the `watch_dog` repository.

---

## E.0 Orientation

The Unitree Go2 is a roughly 15 kg quadruped. Control is over a **WebRTC data channel that
tunnels a DDS-topic pub/sub bus** — *not* ROS 2, and not the official Unitree DDS SDK. This
matters: nearly all public Go2 material assumes `unitree_sdk2py` over CycloneDDS, and that
path was tried and abandoned here.

Three compute nodes are involved:

| Node | Role |
|---|---|
| Go2 control board | Runs the robot's own firmware; WebRTC endpoint on its internal wired subnet |
| Jetson **Orin** | Strapped to the dog's back. Runs the robot control service and camera servers |
| Edge box (AGX Xavier or x86) | Runs perception, the dashboard, and telemetry export |

> **Repository archaeology warning.** `unitree_client.py` (1252 lines) is a **dead-end
> exploration artifact**. Its `send_command()` returns
> `"WebRTC command '{command}' would be sent to robot"` and never publishes anything
> (`unitree_client.py:1216`). The production control path is `go2_service.py`. Do not mine
> the former for design guidance.

---

## E.1 Transport and connection

### Library

[`legion1581/unitree_webrtc_connect`](https://github.com/legion1581/go2_webrtc_connect),
branch `2.x.x`, firmware **1.1.9+** (`GO2_WEBRTC_CONTROL.md:14-17`).

```python
from unitree_webrtc_connect.webrtc_driver import UnitreeWebRTCConnection, WebRTCConnectionMethod
```

Two primitives on the data channel:

```python
# request / response
await conn.datachannel.pub_sub.publish_request_new(TOPIC, {'api_id': N, 'parameter': {...}})

# streaming subscribe
conn.datachannel.pub_sub.subscribe(RTC_TOPIC['LOW_STATE'], callback)
```

**Response envelope** — success is `code == 0`, nested four levels deep
(`go2_service.py:497-502`):

```python
resp['data']['header']['status']['code']     # 0 == success
resp['data']['header']['status']['message']  # sometimes 'msg'
```

### Connection methods

`LocalAP=1`, `LocalSTA=2`, `Remote=3` (`constants.py:21-25`). Production uses **LocalSTA
with an explicit IP**.

### The LocalSTA handshake

A bespoke RSA+AES scheme, not standard WebRTC signaling (`unitree_auth.py:215-267`):

1. `GET http://<ip>:9991/con_notify` → base64 `data1`.
2. The public key PEM is `data1[10:-10]` — **strip exactly 10 characters off each end.**
3. Derive a URL suffix from the last 10 characters of `data1`: chunk into pairs, take the
   *second* character of each pair, map through `["A".."J"]` → index, concatenate
   (`_calc_local_path_ending`, `unitree_auth.py:21-47`).
4. Generate an AES key. `POST http://<ip>:9991/con_ing_<path_ending>` with
   `{data1: aes_encrypt(sdp), data2: rsa_encrypt(aes_key)}`.
5. The response body is AES-encrypted; decrypt to obtain the SDP answer.

> **Expected noise in logs.** The library tries the legacy `POST http://<ip>:8081/offer`
> endpoint first and fails. `"Max retries exceeded"` immediately followed by `✓ Connected!`
> is **normal** (`GO2_WEBRTC_CONTROL.md:111-118`). Do not build alerting on it.

### Post-connect channel validation

The robot sends a challenge key; the client replies with an MD5 → hex → base64 transform on
a `"validation"`-typed message; the robot answers `"Validation Ok."`
(`msgs/validation.py:19-38`). **Topics are rejected until this completes.** A
`"Validation Needed."` error mid-session must trigger re-validation.

### Two distinct heartbeats

Confusing these is a documented source of dropped robots. They are unrelated.

| Heartbeat | Interval | Purpose | Consequence of omission |
|---|---|---|---|
| **Data channel** (`msgs/heartbeat.py:18-43`) | **2 s** | Transport keepalive; carries `{timeInStr, timeInNum}` | Channel dies |
| **Sport** (`go2_service.py:96-103`) | **300 s** | Firmware posture timeout — see §E.5 | **Robot red-lights and falls** |

### Discovery

UDP multicast to **231.1.1.1:10131** returns IP + serial pairs
(`multicast_scanner.py:7-33`).

---

## E.2 Topic table

From the vendored driver `constants.py:64-108`. ★ marks topics the reference deployment
actually used — note how small that subset is relative to what the robot exposes.

| Constant | DDS topic | Use |
|---|---|---|
| ★ `SPORT_MOD` | `rt/api/sport/request` | All locomotion and posture commands |
| ★ `MOTION_SWITCHER` | `rt/api/motion_switcher/request` | Select controller mode |
| ★ `LOW_STATE` | `rt/lf/lowstate` | Battery, IMU, foot force, remote |
| `SPORT_MOD_STATE` | `rt/sportmodestate` | Pose, velocity, gait |
| `LF_SPORT_MOD_STATE` | `rt/lf/sportmodestate` | Low-frequency variant |
| `ULIDAR` | `rt/utlidar/voxel_map` | Native lidar voxel map |
| `ULIDAR_ARRAY` | `rt/utlidar/voxel_map_compressed` | Compressed voxel map |
| `ULIDAR_SWITCH` / `ULIDAR_STATE` | `rt/utlidar/switch`, `.../lidar_state` | Lidar enable / health |
| `ROBOTODOM` | `rt/utlidar/robot_pose` | Odometry pose |
| `LOW_CMD` | `rt/lowcmd` | Joint-level control |
| `WIRELESS_CONTROLLER` | `rt/wirelesscontroller` | Physical remote |
| `FRONT_PHOTO_REQ` | `rt/api/videohub/request` | Still capture |
| `VUI` | `rt/api/vui/request` | LED / voice UI |
| `OBSTACLES_AVOID` | `rt/api/obstacles_avoid/request` | Obstacle avoidance mode |
| `AUDIO_HUB_REQ` | `rt/api/audiohub/request` | Speaker / megaphone |
| `SLAM_*` — see below | `rt/uslam/...` | SLAM / navigation stack |
| `ARM_COMMAND` / `ARM_FEEDBACK` | `rt/arm_Command`, `rt/arm_Feedback` | Optional arm |
| `GAS_SENSOR`, `UWB_STATE`, `SELF_TEST`, `GRID_MAP` | — | Miscellaneous |

`VUI_COLOR` accepts white, red, yellow, blue, green, cyan, purple
(`constants.py:186-193`). `AUDIO_API` uses IDs 1001–5003 (`constants.py:196-203`).

### The SLAM topic surface — directly relevant to mapping

The robot exposes a complete SLAM stack the reference deployment never touched. **These are
the topics the map-building feature should investigate first**, before committing to
running an external SLAM pipeline on the backpack compute:

| Topic | Content |
|---|---|
| `rt/uslam/frontend/cloud_world_ds` | Downsampled world point cloud, frontend |
| `rt/uslam/frontend/odom` | Frontend odometry |
| `rt/uslam/cloud_map` | Accumulated cloud map |
| `rt/uslam/localization/cloud_world` | Localization world cloud |
| `rt/uslam/localization/odom` | Localization odometry |
| `rt/uslam/navigation/global_path` | Planned global path |
| `rt/lio_sam_ros2/mapping/odometry` | LIO-SAM mapping odometry |
| `rt/mapping/grid_map` | 2D grid map |

The presence of `rt/lio_sam_ros2/...` indicates the firmware runs a LIO-SAM derivative
internally. **Whether these topics are populated on stock firmware, at what rate, and in
which coordinate frame is unverified** — no one on this project has subscribed to them.
Determining this empirically is a day-one task for the mapping feature, because using the
robot's own SLAM output would be dramatically cheaper than running FAST-LIO2 or KISS-ICP on
the backpack Orin alongside perception.

---

## E.3 Sport-mode API ID table

`constants.py:110-160`. **This table is the single most reusable artifact recovered from
the deployment** — it is not well documented publicly.

| ID | Name | ID | Name | ID | Name |
|---|---|---|---|---|---|
| 1001 | Damp | 1018 | TrajectoryFollow | 1036 | FingerHeart |
| 1002 | BalanceStand | 1019 | ContinuousGait | 1039 | StandOut |
| 1003 | StopMove | 1020 | Content | 1042 | LeftFlip |
| 1004 | StandUp | 1021 | Wallow | 1043 | RightFlip |
| 1005 | StandDown | 1022 | Dance1 | 1044 | BackFlip |
| 1006 | RecoveryStand | 1023 | Dance2 | 1045 | LeadFollow / FreeWalk |
| 1007 | Euler | 1024 | GetBodyHeight | 1050 | Standup |
| 1008 | Move | 1025 | GetFootRaiseHeight | 1051 | CrossWalk |
| 1009 | Sit | 1026 | GetSpeedLevel | 1301 | Handstand |
| 1010 | RiseSit | 1027 | SwitchJoystick | 1302 | CrossStep |
| 1011 | SwitchGait | 1028 | Pose | 1303 | OnesidedStep |
| 1012 | Trigger | 1029 | Scrape | 1304 | Bound |
| 1013 | BodyHeight | 1030 | FrontFlip | 1305 | MoonWalk |
| 1014 | FootRaiseHeight | 1031 | FrontJump | | |
| 1015 | SpeedLevel | 1032 | FrontPounce | | |
| 1016 | Hello | 1033 | WiggleHips | | |
| 1017 | Stretch | 1034 | GetState | | |
| | | 1035 | EconomicGait | | |

### Two traps in this table

> **Trap 1 — `MOTION_SWITCHER` has its own ID space.** Selecting the controller mode is
> `api_id: 1002` with `parameter: {'name': 'normal'}` on the **MOTION_SWITCHER** topic
> (`go2_service.py:349-352`). That `1002` is **not** BalanceStand. Different topic,
> different namespace. Conflating them is easy and has real consequences (§E.5).

> **Trap 2 — a mislabeled mapping exists in the reference repo.**
> `go2_web_battery.py:164-170` maps `"sit"→Damp(1001)` and `"damp"→RecoveryStand(1006)`.
> The labels are transposed relative to the IDs. The correct mapping is in
> `go2_service.py:82-87`.

### Move parameters

```python
{'api_id': 1008, 'parameter': {'x': vx, 'y': vy, 'z': vyaw}}
```

Body-frame, m/s and rad/s (`go2_service.py:540-543`). **`BalanceStand` (1002) must be sent
once before the first `Move`** (`go2_service.py:535-539`) — but see §E.5, because doing
this unconditionally is what kills standing robots.

Velocity envelope used in production (`web_app.py:702-704`): `vx ≤ 0.25`, `vy ≤ 0.2`,
`vyaw ≤ 0.5`. These are conservative demo limits, not hardware maxima.

---

## E.4 Sensors

### Onboard camera

```python
conn.video.switchVideoChannel(True)
conn.video.add_track_callback(recv_camera_stream)
# in callback:
frame = await track.recv()
img = frame.to_ndarray(format='bgr24')
```

Source frames are **1920×1080** (`TELEMETRY_SCHEMA.md:91-92`), H.264 on the WebRTC leg.
Under the hood `switchVideoChannel` publishes a `"vid"`-typed message with payload
`"on"`/`"off"` and adds a `recvonly` transceiver (`webrtc_datachannel.py:171-178`).

Production re-encodes to JPEG on a dedicated encoder thread behind a `maxsize=2` queue that
drops when full (`go2_service.py:72, 136-153`), then serves MJPEG.

> **Practical annoyance.** libav floods stderr with
> `"No accelerated colorspace conversion found from yuv420p to bgr24"`. The reference
> implementation redirects C-level stderr through a pump thread to suppress it
> (`go2_service.py:31-59`).

### Lidar — available, and never used

The driver has complete lidar support the reference deployment never touched. This is a
significant opportunity for the new platform, and the details are non-obvious:

- Binary data-channel frames are dispatched by a 4-byte header: `(2,0)` means lidar,
  anything else is a normal message (`webrtc_datachannel.py:123-128`).
- A lidar frame is a 4-byte length + JSON header + compressed payload. Decoding yields
  `{"points", "uvs", "positions"}` via
  `bits_to_points(decompressed, origin, resolution=0.05)`
  (`lidar/lidar_decoder_native.py:31-59`).
- So the native format is an **occupancy-voxel bitfield at 5 cm default resolution with an
  origin offset** — *not* XYZ float triples. Plan conversion accordingly.
- Two decoders exist: a `libvoxel` WASM decoder and a native one
  (`webrtc_datachannel.py:188-200`).

> **You must call `disableTrafficSaving(True)` before subscribing to `ULIDAR`, or no
> frames will arrive** (`webrtc_datachannel.py:155-169`). This is the kind of undocumented
> precondition that costs a day.

No coordinate frame, no publish rate, and no extrinsic calibration for the native lidar is
documented anywhere in the reference deployment. **Treat all three as unknowns requiring
empirical determination.**

### RealSense over RTSP

Three mounts at **15 fps** on the Orin, port 8554: `/color` (x264 **CPU** encode — the
expensive one), `/ir` (NVENC, 848×480), `/depth` (NVENC, colorized).

Client settings that matter (`camera.py:241-256`):

```python
os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;tcp|stimeout;5000000'
cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # latency
```

`stimeout` is in **microseconds**. The 5 s value shown is too aggressive for a loaded
server; 60 s is recommended (`PERFORMANCE_ANALYSIS.md:181-183`).

> **The RTSP server burns ~103% CPU with zero clients connected**, pushing the Orin's
> 4-core load to 3.88/4.0. Root cause: `GLib.timeout_add` timers and a
> `while True: poll_for_frames()` producer that never stop when no one is watching
> (`PERFORMANCE_ANALYSIS.md:56-81`). Two fix attempts failed. The shipped workaround is a
> manual start/stop button, which makes camera switching take **30+ seconds**.
> **The new platform must not repeat this design.** Sensor servers must be demand-driven.

---

## E.5 The standing-crash saga

Four commits, one root-cause chain. This is the most valuable operational knowledge in the
entire deployment and it generalizes: **a legged robot's firmware has posture-dependent
safety faults that are invisible from the API surface.**

### Act 1 — the keepalive kills a standing robot (`de7107c`)

The robot drops to MCF mode after 30–45 s idle, so a keepalive re-sent
`set_motion_mode('normal')` on MOTION_SWITCHER every 30 s.

**Root cause:** re-selecting the motion controller *while the robot holds `BalanceStand` or
`StandUp` posture* triggers a firmware safety fault. Red light, robot collapses.

**Fix:** track posture (`idle` / `standing` / `sitting`), remove `stand` from the keepalive
command set, and make entering standing *stop* the keepalive. Guarded at three layers —
enqueue, queue consumer, and reconnect (`go2_service.py:160-164, 438-444, 397-400`).

### Act 2 — posture desync on operator handoff (`644eeff`)

An operator picks up the physical remote and walks the dog. Software still believes
`posture == 'standing'` and suppresses its pings forever.

**Fix:** any joystick or button activity on `LOW_STATE.wireless_remote` clears the standing
guard and stops both heartbeats (`go2_service.py:420-429`); any non-`stand` command resets
posture to `idle` (`go2_service.py:661-665`).

### Act 3 — the move watchdog was the actual killer (`6f19926`)

**Root cause chain, and it is worth reading twice:**

1. The edge box runs a deadman watchdog that POSTs `/stop` every 200 ms once 0.6 s elapses
   without a move command (`web_app.py:708-718`).
2. `/stop` routes through the move queue.
3. The move queue sends **`BalanceStand(1002)` before `Move(0,0,0)`**
   (`go2_service.py:535-539`).
4. **`BalanceStand` sent to a robot already in `StandUp` posture is a safety fault.**

So a *single D-pad press* armed a loop that would eventually fell a standing dog.

**Fix, in three parts:** `/stop` no-ops when standing (`go2_service.py:736-742`); `/move`
returns HTTP 409 when standing (`go2_service.py:707-710`); and any posture command zeroes
the move timestamp to disarm the watchdog (`web_app.py:748-750`).

### Act 4 — but the robot also needs sport traffic to survive (`b677be5`)

With all software interference removed, field logs still showed red-lighting roughly **10
minutes** after StandUp.

**Root cause: a firmware-level sport-command timeout.** With no further SPORT_MOD traffic,
the controller safety-faults on its own.

**Fix:** re-send `StandUp` on **SPORT_MOD** — never MOTION_SWITCHER — every **300 s**,
comfortably inside the ~600 s window. The rationale is preserved verbatim in the source
and is worth quoting:

> *"Field logs show the robot can stay up for roughly 10 minutes after StandUp and then
> enter a red-light fault/fall when no further WebRTC sport traffic is sent. Re-selecting
> MOTION_SWITCHER 'normal' while standing previously caused falls, so this heartbeat
> intentionally re-sends the posture command on SPORT_MOD instead."*
> — `go2_service.py:96-103`

The heartbeat self-terminates on posture change, remote takeover, session loss, a non-stand
command, or a failed stand.

### What this means for the platform

The Go2 driver must own a **posture state machine with firmware-specific transition
guards**, and the rest of the system must never send raw commands that bypass it. This is
the strongest argument in the entire specification for putting safety enforcement *inside
the driver* rather than in the UI or the mission executor — which is, independently, also
what Anthropic's Model Hardware Standard concluded.

---

## E.6 Timing and guard constants

| Constant | Value | Source |
|---|---|---|
| Data channel heartbeat | **2 s** (protocol requirement) | `msgs/heartbeat.py:21` |
| `KEEPALIVE_INTERVAL_SECONDS` | 30 s (reduced from 20 as "less aggressive") | `go2_service.py:94` |
| `STANDING_HEARTBEAT_INTERVAL_SECONDS` | **300 s** | `go2_service.py:103` |
| `REMOTE_ACTIVITY_TIMEOUT` | 5.0 s | `go2_service.py:104` |
| `REMOTE_AXIS_THRESHOLD` | 0.05 | `go2_service.py:105` |
| `COMMAND_RESULT_TIMEOUT` | 8.0 s | `go2_service.py:110` |
| `_ROBOT_CMD_MIN_GAP` | 2.0 s between sport commands | `go2_service.py:116` |
| Command loop tick | 0.03 s (30 Hz) | `go2_service.py:585` |
| Mode-settle pause before sport command | 0.1 s | `go2_service.py:492` |
| Connect retry backoff | `min(5 × attempt, 30)` s | `go2_service.py:385` |
| Deadman move timeout | 0.6 s, watchdog ticks at 0.2 s | `web_app.py:700, 718` |
| Command cooldown | 1.5 s | `web_app.py:701` |

**Per-command latency:** a fresh connection per command costs **2–3 s**; a persistent
connection costs **under 1 s** (`GO2_WEBRTC_CONTROL.md:99-105`). Always hold the
connection.

---

## E.7 Failure modes and remedies

| Symptom | Cause | Remedy |
|---|---|---|
| `RuntimeError: cannot reuse already awaited coroutine` | Watchdog logic added to the service | Restore known-good file |
| `"Could not get SDP from the peer"` | WebRTC service saturated by too many connect attempts | **Reboot the robot** |
| Commands silently ignored | Robot in MCF mode, **or the Unitree phone app is open** and holding the WebRTC slot | Select `normal` mode; close the app |
| `sit` / `shake` return `code: -1` | SPORT controller timed out | Re-select motion mode `normal`. The reference tolerates these via `LENIENT_STATUS_CODES = {'sit': {-1}, 'shake': {-1}}` (`go2_service.py:106-109`) |
| Drops to MCF after 30–45 s idle | Firmware | Keepalive loop (but see §E.5 Act 1) |
| Red-light fall ~10 min after standing | Firmware sport timeout | 300 s SPORT_MOD posture heartbeat |
| Event-loop errors under Flask | **WebRTC connection objects cannot cross asyncio event loop boundaries** | One persistent loop in a daemon thread, bridged with `queue.Queue` |

Recovery convention: on unexpected sport-command failure, the reference auto-sends
`RecoveryStand(1006)` (`go2_service.py:505-513`).

### Firmware error codes

Enumerated in `constants.py:28-62`. These surface as robot-reported faults and the platform
should map them to operator-legible messages rather than showing raw codes:

| Code | Meaning | Code | Meaning |
|---|---|---|---|
| `100_1` | DDS message timeout | `400_2` | Point cloud data abnormal |
| `300_1` | Overcurrent | `600_4` | Overheating software protection |
| `300_100` | Motor communication interruption | `600_8` | Low battery software protection |

After a fall or red light: power cycle, let the dog auto-stand, then **issue Crouch first**
(`DEMO_RUNBOOK.md:160-165`). Stand mode blocks locomotion by design — crouch before
driving.

> **A standing instruction from the reference deployment, preserved because it was earned:**
> *"Do not add watchdog logic, automatic restarts, or complex error recovery to this
> service. Those features caused the service to fail."* (`GO2_SERVICE_README.md:135-137`)
>
> Read in context this is not an argument against reliability engineering — it is an
> argument that **recovery logic belongs in a supervisor process, not inside the session
> that owns the robot connection.** The new platform separates these explicitly.

---

## E.8 Telemetry the robot actually provides

Subscribed from `LOW_STATE` (`rt/lf/lowstate`):

| Path | Meaning | Unit |
|---|---|---|
| `data['bms_state']['soc']` | State of charge | % (0–100) |
| `data['power_v']` | Pack voltage | ⚠️ **ambiguous, see below** |
| `data['bms_state']['current']` | Pack current | mA (negative = charging) |
| `data['bms_state']['bq_ntc']` | Battery temperature | — |
| `data['bms_state']['cycle']` | Charge cycles | count |
| `data['wireless_remote']` | Raw remote packet | 24+ bytes |

> **Unresolved unit ambiguity.** One consumer divides `power_v` by 1000 to display volts
> (implying millivolts at source, `go2_web_battery.py:81`), while recorded telemetry shows
> values like `31.686502` and `25.2` (implying volts already). **Pin this down empirically
> before trusting the field.**

### Wireless remote byte layout (reverse-engineered)

`go2_service.py:193-223`:

- Bytes `[2]` and `[3]` — button bitfields; nonzero means pressed.
- Offsets `4, 8, 12, 20` — four little-endian `float32` joystick axes.
- Activity is declared if any button is set or any `|axis| > 0.05`.

### The significant gap

`SPORT_MOD_STATE` (`rt/sportmodestate`) carries **pose, IMU, foot force, and gait**. The
reference deployment **never subscribed to it.** There is therefore no pose, no IMU, no
foot force, and no gait data anywhere in the prior system. For a platform that intends to
do waypoint navigation, subscribing to this topic is a **day-one requirement**, and no
prior art exists in this codebase to copy.

---

## E.9 Perception stack notes

| Purpose | Model |
|---|---|
| Main detection | `yolo11m.pt` @ imgsz 1280, conf 0.25, IoU 0.45 |
| PPE compliance | `yolov8s-worldv2.pt` (YOLO-World, open-vocabulary) |
| Gesture | `yolo11n-pose.pt` |
| Scene narration | `qwen2.5vl:3b` via Ollama at `127.0.0.1:11434` |

> **Naming trap.** The file `yoloe_detector.py` is **not YOLOE.** Its own docstring says
> "Hybrid YOLO11 Detector with Visual Similarity Filtering." Its "visual prompt" mode is
> **SIFT + FLANN homography matching against a reference PNG**, wrapped in a synthetic
> torch tensor (`yoloe_detector.py:481-520, 598-615`). The only genuine `set_classes()`
> call in the codebase is YOLO-World's PPE vocabulary.

### Two live defects worth not inheriting

**Device auto-detect probes the wrong library:**

```python
device = "cuda" if cv2.cuda.getCudaEnabledDeviceCount() > 0 else "cpu"   # yoloe_detector.py:70
```

Stock pip OpenCV reports **0** CUDA devices regardless of hardware, so on a perfectly
capable Jetson this silently pins all inference to CPU. Probe `torch.cuda.is_available()`
instead.

**`cv2.SIFT_create()` is constructed inside the per-frame loop** (`yoloe_detector.py:531`).

### GPU contention

There is **no CUDA context management** in the reference: no `empty_cache()`, no warmup, no
TensorRT engine loading, no inference locks across models. The only runtime lock is
`SceneNarrator._vlm_lock`, held across the whole Ollama request "so the VLM is never
double-booked" (`scene_narrator.py:114, 313`). The three YOLO models run unguarded and
concurrently.

**Frame skipping is the entire GPU budget mechanism**, stated explicitly in comments as
"Frame-skipped for GPU budget" (`web_app.py:250`). Measured production throughput:
**3.8 detection FPS**.

**Field observation, not reproduced in code review:** during a 2026 deployment, running the
main detector on GPU appeared to corrupt CUDA state such that a second detector's GPU
inference failed with `cudaErrorLaunchFailure`, and the PPE detector had to be pinned to
CPU permanently. An independent audit of this codebase found **no code-level evidence** of
context poisoning and no mitigation for it — no `torch.cuda.empty_cache()`, no reload-on-
failure. Treat the mechanism as **unverified**: the symptom was real, the diagnosis was
not confirmed. Regardless, the new platform should adopt **one owner per GPU context** as
an architectural rule, which makes the question moot.

### A wiring hazard to design against

Perception calls the actuator **directly**: a keypoint geometry check POSTs a literal
`{'command': 'shake'}` to a hardcoded URL (`web_app.py:1563-1567`). Worse, the arming flag
for that behavior is a module global flipped by the *scene-narrator mode* endpoint
(`web_app.py:960-963`) — meaning **changing a VLM narration setting arms or disarms a
physical robot action.** The VLM's own gesture path was deliberately left unwired because
it produced "phantom shakes" from hallucination.

---

## E.10 Abstraction seams — where Go2 leaks

Ordered by severity. These are the specific reasons the new platform needs a driver
abstraction, each grounded in real code.

| # | Leak | Evidence | Seam required |
|---|---|---|---|
| **G1** | Perception calls the actuator directly; there is no event bus | `web_app.py:693, 1563-1567` | Perception emits events; a policy layer maps events to capabilities |
| **G2** | Robot kinematic limits and safety timings live in the vision web app | `web_app.py:700-705, 785-787` | Capability descriptor owned by the driver |
| **G3** | Posture state machine is firmware-shaped and lives in the HTTP service; posture strings compared with `==` in six places | `go2_service.py:117, 162, 399, 441, 478, 558, 709, 736` | Generic state machine with per-robot transition guards |
| **G4** | Command vocabulary is a 4-entry dict of Unitree IDs, plus per-command tolerated error codes | `go2_service.py:82-87, 106-109` | Capability registry of robot-agnostic verbs |
| **G5** | VLM prompts hardcode species and camera height ("You ARE a Unitree GO2 robot dog… at ground level") | `scene_narrator.py:43, 59-60, 85-86`; `config.yaml:36-41` | Templated persona injected from the robot descriptor |
| **G6** | Gesture geometry encodes a 12-inch camera height; all rules invert on a chest-height mount | `gesture_detector.py:6-9, 34, 166, 179` | Camera extrinsics as explicit parameters |
| **G7** | Camera sources are an enum of Go2/Jetson strings, including a hardcoded robot serial (twice) | `camera.py:23-37, 81, 185` | Camera as URI + driver plugin |
| **G8** | Single-robot by construction — `robot_id = "go2-unit-01"` hardcoded, and every component is a process-wide singleton | `telemetry_exporter.py:56, 597`; singletons in 7 modules | Instance-scoped components keyed by robot ID |
| **G9** | Endpoints hardcoded despite config existing for them — `config.yaml`'s `go2:` and `rtsp:` blocks are **read by no Python file** | `config.yaml:7-10`; `web_app.py:705, 821` | Single config load path, no literals |
| **G10** | Five different reconnect policies for one problem; two paths have no reconnect at all | `camera.py:429, 560, 613`; `rtsp_proxy.py:48` | One reconnect policy object |
| **G11** | No frame queue anywhere — a single `current_frame` slot with a full `.copy()` per read | `camera.py:20, 692-697` | Multi-consumer frame bus; required for recording and replay |
| **G12** | Toggling a perception mode silently arms a physical action | `web_app.py:623, 960-963` | Explicit arming, separate from display settings |
| **G13** | Lidar, odometry, SLAM, audio, LEDs, arm, gas sensor and full sport state are exposed by the driver and entirely unmodeled | §E.2 | Model the full topic surface even if v1 implements a subset |

---

## E.11 Contradictions to resolve

Carried forward as open questions; each is a place the reference documentation disagrees
with itself, and the new platform should determine ground truth empirically.

1. **Three IP generations** litter the docs (`192.168.86.x` → `192.168.1.x` →
   `192.168.50.x`), plus a ZeroTier overlay at `10.228.36.x` for the remote site.
2. **RTSP frame rate**: 15 fps (`PERFORMANCE_ANALYSIS.md:62`) versus 30 fps
   (`RTSP_QUICK_REFERENCE.md:69`).
3. **Detection model**: `yolo11m.pt` (`config.yaml:56`) versus `yolo11s.pt`
   (`TELEMETRY_SCHEMA.md:87`) versus `yolo11s-seg.pt` (`config.py:24`).
4. **Battery voltage units**: millivolts versus volts (§E.8).
5. **Command mapping**: `go2_web_battery.py` transposes sit and damp (§E.3).
6. **systemd persistence**: listed as pending in one document, auto-starting in another.

Additionally, note for the threat model: **credentials are stored in plaintext throughout
the reference codebase and documentation** — device passwords, the WiFi PSK, and an SSH
password used as a literal default fallback in application code. A prior commit already
removed one set of hardcoded credentials; more remain. The new platform must not inherit
this practice.

### Artifacts that must be retrieved before designing the sensor layer

> **`rtsp_rs.py` — the RealSense RTSP server, and the single worst performance bottleneck
> in the reference system — does not exist in the repository.** It lives only on the
> backpack Orin's filesystem. Retrieve it before making any sensor-layer decisions, because
> the 103%-CPU-at-idle behavior documented in §E.4 can only be diagnosed from that source.
