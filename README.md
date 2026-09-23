# Project Watch Dog

Robot patrol demo: a Unitree Go2 walks a booth while an edge box detects
people and objects, narrates the scene with Cosmos, answers hand gestures,
and lets an operator drive the dog from a browser. Built by NTT DATA Physical
AI ("AI that sees, reasons, acts").

---

## What it delivers
- **Live robot video** from the Go2's camera, with detection boxes drawn on it.
  A clear `VIDEO LOST` overlay appears when the feed goes stale.
- **Detection**: YOLO-E / YOLO11 hybrid, driven by new frames at the camera's
  own rate (about 14 FPS).
- **Scene narration** by Cosmos Reason 2 8B (NVIDIA vLLM), shared with
  Elastic-Vision on the Thor.
- **Gesture mode**: an open hand held close to the camera makes the dog shake
  hands. MediaPipe detects it, with a 3 s cooldown. Detection is on only while
  the Gesture tab is open.
- **Driving and commands**: a D-pad, E-stop, and stand / crouch / sit / shake.
  Every command is safety-gated (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)).
- **Vendor demo skins**: Default, Microsoft Azure (Ignite) and AWS (re:Invent),
  plus a "Powered by NVIDIA" badge.
  See [static/themes/README.md](static/themes/README.md).
- **Operator sign-in over HTTPS**, using certificates from a private demo CA.

---

## Topology (current)

```
Go2 robot (firmware 1.1.15, 192.168.123.161 internal)
   │  DDS (commands + telemetry)  +  WebRTC video-only (AES key)
   ▼
Orin backpack  — go2_service.py in Docker (deploy/orin/)
   HTTPS :5001, demo-CA certificate
   public: /status /battery /video_feed    control: token + drive permits
   │  HTTPS (CA-verified), keep-alive
   ▼
Jetson AGX Thor — watchdog container (deploy/thor/), https://<thor>:8443
   detection · Cosmos narration (Elastic-Vision's vLLM) · gesture · auto-arm
   │  HTTPS + operator login
   ▼
Operator laptop (browser)
```

| Host | Addresses | Role |
| --- | --- | --- |
| Go2 Orin backpack | 192.168.50.207 (Cradlepoint), 10.0.0.57 (home), 192.168.193.111 (ZeroTier) | Robot link (`go2_service`) |
| Jetson AGX Thor | 192.168.50.209 (Cradlepoint), 10.0.0.109 (home WiFi), 192.168.1.234 (ethernet) | Dashboard, AI, the only controller |
| AGX Xavier (legacy) | 192.168.50.208 | Retired from driving. It can't reach the HTTPS robot link until it's updated. |

The Thor runs Watch Dog **or** Elastic-Vision's app stack, never both. Switch
between them with `demo-mode`. Azimuth and Watch Dog never drive the dog at the
same time: their Orin systemd units declare `Conflicts=`.

---

## Repo layout (highlights)
| Path | Purpose |
| --- | --- |
| `web_app.py` | Flask dashboard, detection pipeline, robot proxy, gesture, deadman. |
| `camera.py` | Camera manager (Go2 / RTSP / Mac), with frame seq/timestamps and a capture generation. |
| `robot_host.py` | Robot-address resolver. It keeps separate HTTPS sessions: public (no token) and control (token). |
| `go2_service.py` | Robot link on the Orin: DDS via go2dds, stop machine, permits, video. |
| `hand_detector.py` | MediaPipe hand landmarker (primary) with a YOLO-World fallback. |
| `scene_narrator.py` | Narrator (OpenAI-compatible backend, i.e. Cosmos on vLLM). |
| `auth.py` | Operator login, CSRF, throttling, and the supervisor token. |
| `ui_profiles.py`, `static/themes/` | Vendor demo skins. |
| `deploy/thor/` | Thor container, `demo-mode`, compose, Thor overlay config. |
| `deploy/orin/` | Orin image, systemd unit, and the safe `build.sh` deploy. |
| `deploy/systemd/watchdog-autostart.sh` | Auto-arm supervisor (Thor container and legacy AGX). |
| `docs/ARCHITECTURE.md` | Robot-link protocol and safety model. |
| `docs/LEARNINGS.md` | What we learned the hard way. |
| `DEMO_RUNBOOK.md` | Event-day runbook. **Local only** (gitignored, because it holds credentials). |

The shared DDS library **go2dds** lives outside this repo, in
`~/Development/go2dds`, a local git repo also meant for Azimuth. The Orin build
ships the commit pinned in `deploy/orin/GO2DDS_REV`.

---

## Everyday operation

```bash
ssh thor 'demo-mode status'      # which stack is up; is Cosmos serving
ssh thor 'demo-mode watchdog'    # bring up Watch Dog (Elastic-Vision app stack down)
ssh thor 'demo-mode elastic'     # back to Elastic-Vision
```

Open `https://<thor-ip>:8443` and sign in. Trust the demo CA once per laptop
to get a padlock (see [deploy/thor/README.md](deploy/thor/README.md)). After
the dog powers on, the auto-arm supervisor starts detection on its own within
about a minute.

## Deploying

- **Thor**: code is bind-mounted from `~/watch_dog`. Copy the changed files,
  then `docker compose restart` in `deploy/thor`. Details are in
  [deploy/thor/README.md](deploy/thor/README.md).
- **Orin**: `SSHPASS=<orin password> deploy/orin/build.sh unitree@<orin-ip>`.
  The script builds, runs a preflight, promotes, checks health and rolls back
  automatically on failure. It needs the dog on, because the health check
  requires both the robot link and video.
  Details are in [deploy/orin/README.md](deploy/orin/README.md).

## Security notes
- This repository is **public**. No passwords, tokens, AES keys, WiFi keys,
  `auth.json` or certificates/keys go in git. Device credentials live outside
  the repo.
- Secrets on the devices:
  - Thor: `/state/auth.json`, `/state/robot_token`, `/state/tls/`.
  - Orin: `/etc/go2_service.env`, `/etc/watchdog-go2/tls/`.
- The demo CA key stays on Raleigh's Mac (`~/.watchdog-ca/`).
- The Thor is the only controller. Only it holds the robot control token.
