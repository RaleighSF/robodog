# Project Watch Dog  
Intelligent visual patrol system that combines Unitree GO2 telemetry, Jetson-based RTSP feeds, and an AGX-hosted detection dashboard to monitor factory floors in real time.

---

## 📸 What It Delivers
- **Native GO2 WebRTC feed** proxied from the backpack Orin for ultra-low latency viewing.
- **RTSP Color / IR / Depth feeds** pulled from the Jetson stack with automatic reconnection.
- **Hybrid YOLO-E detections** (visual + prompt-driven) drawn over the live stream.
- **Robot control hooks** (stand, crouch, sit, shake) with motion-mode keepalive logic.
- **Battery + status telemetry** surfaced in the dashboard header and REST APIs.

---

## 🗺️ System Topology
```
GO2 Robot (192.168.50.75)
        │ WebRTC (STA)
        ▼
Orin Backpack (192.168.50.207)
    - ~/go2_service.py  → HTTP API :5001
    - RTSP server :8554  (color/ir/depth)
        │ HTTP/RTSP
        ▼
AGX Xavier (192.168.50.208)
    - ~/dev/watch_dog/start_web_app.py :8000
    - Runs YOLO detection, proxy endpoints, UI
        │ HTTPS/Browser
        ▼
Operator Laptop
```

---

## 📁 Repo Layout (highlights)
| Path | Purpose |
| --- | --- |
| `go2_service.py` | GO2 WebRTC + command service (runs on Orin). |
| `web_app.py` | Flask dashboard (runs on AGX). |
| `camera.py` | Camera manager that switches Mac, RTSP, GO2 WebRTC sources. |
| `templates/index.html` | Dashboard UI (Inter-based, dark theme). |
| `config.yaml` | Sanitized template for detection + GO2 settings (fill secrets via env). |
| `rtsp_proxy.py` | Utility to bridge Jetson RTSP → HTTP MJPEG if needed. |
| `visual_prompts/` | Prompt images used by the detector. |

---

## ⚙️ Prerequisites
- macOS / Linux dev machine with Python 3.11+ for local edits.
- Access to both hosts:
  - `unitree@192.168.50.207` – Orin.
  - `raleigh@192.168.50.208` – AGX.
  - Passwords are **not** in this repo — see the gitignored `CONNECTIONS.md` (or use SSH keys).
- GO2 robot reachable at `192.168.50.75` (STA mode).
- Git LFS not required (large weights kept out of repo).

---

## 🚀 Quick Start

### 1. Clone & Install (developer box)
```bash
git clone https://github.com/RaleighSF/robodog.git
cd watch_dog
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure
Edit `config.yaml` or provide env vars:
```yaml
vision:
  source: rtsp://192.168.50.207:8554/color
  openai_api_key: ""      # leave empty, set OPENAI_API_KEY env instead
go2:
  service_url: http://192.168.50.207:5001
```
```bash
export OPENAI_API_KEY="sk-..."    # optional if using NLP prompts
```

### 3. Deploy services
#### Orin (192.168.50.207)
```bash
scp go2_service.py unitree@192.168.50.207:~
ssh unitree@192.168.50.207 <<'EOF'
pkill -f go2_service.py || true
nohup python3 ~/go2_service.py > ~/go2_service.log 2>&1 &
EOF
```

#### AGX (192.168.50.208)
```bash
scp -r . raleigh@192.168.50.208:~/dev/watch_dog
ssh raleigh@192.168.50.208 <<'EOF'
cd ~/dev/watch_dog
source venv/bin/activate
pkill -f start_web_app.py || true
nohup python start_web_app.py > web_app_agx.log 2>&1 &
EOF
```
Dashboard becomes available at `http://192.168.50.208:8000`.

---

## 🧭 Operating the Dashboard
1. Open the site and choose **Native Go2 Camera** or any RTSP channel.
2. Press **Start Patrol** to spin up the selected feed plus detector.
3. Use the left panel to review detections, switch cameras, or stop patrol.
4. Stop button now triggers `/go2/stream/unregister` to pause GO2 encoding and free RTSP bandwidth.

---

## 🔧 Maintenance & Troubleshooting

| Symptom | Checks |
| --- | --- |
| GO2 feed blank | `ssh unitree@... tail -f ~/go2_service.log` – confirm `[Stream] register route ...` messages. |
| RTSP feeds take 30s to start | Ensure GO2 view is stopped so encoder gating disables the WebRTC channel. |
| Dashboard unresponsive | `ssh raleigh@... tail -f ~/dev/watch_dog/web_app_agx.log` and restart service. |
| Secret detected on push | Keep real keys out of `config.yaml`; store in env or secrets manager. |

---

## 🔐 Security Notes
- All secrets (OpenAI, etc.) must be injected via env vars (`export OPENAI_API_KEY=...`) or gitignored files.
- Git history has been sanitized—future pushes with embedded keys will be blocked by GitHub push protection.

---

## 🛣️ Future Enhancements
- Automated GO2 encoder gating verification logs surfaced in UI.
- Motion keepalive + auto crouch when idle.
- Optional GitHub Actions deployment scripts.

Happy patrolling! 🐕‍🦺
