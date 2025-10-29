# GO2 Service - Reference Implementation

This directory contains a reference copy of the working GO2 WebRTC service that runs on the ORIN host.

## Overview

The `go2_service.py` file is the **stable, optimized version** of the GO2 WebRTC service that provides:
- Live video feed from GO2 robot camera
- Battery telemetry (SOC, voltage, current)
- Robot command execution (stand, crouch, sit, shake)
- Status endpoint for health monitoring

## Deployment Location

**Production Host:** unitree@192.168.86.21 (ORIN)
**Production Path:** `/home/unitree/go2_service.py`
**Port:** 5001

## Why This Reference Copy Exists

During development, the service on the ORIN was accidentally modified with complex watchdog logic that caused critical errors:
- `RuntimeError: cannot reuse already awaited coroutine`
- WebRTC connection failures and restart loops
- Frame serving completely broken

This reference copy serves as the **known-good version** that can be quickly restored if the ORIN service becomes corrupted again.

## Restoring the Service

If the GO2 service on ORIN stops working:

```bash
# 1. Copy this reference version to ORIN
sshpass -p "123" ssh unitree@192.168.86.21 "cat > ~/go2_service.py" < go2_service.py

# 2. Kill any running instances
sshpass -p "123" ssh unitree@192.168.86.21 "pkill -f go2_service.py"

# 3. Start the service
sshpass -p "123" ssh unitree@192.168.86.21 "cd ~ && python3 go2_service.py > go2_service.log 2>&1 &"

# 4. Verify it's working
curl http://192.168.86.21:5001/status
# Should return: {"battery_soc":XX,"connected":true,"has_video":true}
```

## Service Architecture

### Simple & Reliable Design

This version intentionally avoids complex features like:
- ❌ Watchdog threads
- ❌ Automatic restarts
- ❌ Port conflict detection
- ❌ Restart endpoints

Instead, it focuses on:
- ✅ Stable WebRTC connection
- ✅ Efficient frame capture (30 FPS)
- ✅ Low logging overhead
- ✅ Simple error handling

### Performance Optimizations

- **30Hz command processing loop** (0.03s sleep)
- **30 FPS video generation** (0.03s sleep)
- **85% JPEG quality** (balance of quality vs bandwidth)
- **3 second command timeout** (faster response)
- **Minimal logging** (production-ready)

### API Endpoints

#### GET `/battery`
Returns battery telemetry:
```json
{
  "soc": 33,
  "voltage": 25.2,
  "current": 1.5,
  "connected": true
}
```

#### GET `/video_feed`
MJPEG stream (multipart/x-mixed-replace)
- 30 FPS target
- 85% JPEG quality
- Optimized chunk size

#### GET `/status`
Health check endpoint:
```json
{
  "connected": true,
  "battery_soc": 33,
  "has_video": true
}
```

#### POST `/command`
Execute robot commands:
```json
{
  "command": "stand" | "crouch" | "sit" | "shake"
}
```

## Troubleshooting

### Service won't start
```bash
# Check if port 5001 is in use
sshpass -p "123" ssh unitree@192.168.86.21 "lsof -ti tcp:5001"

# Kill the process holding the port
sshpass -p "123" ssh unitree@192.168.86.21 "lsof -ti tcp:5001 | xargs kill"
```

### No video frames
```bash
# Check the logs
sshpass -p "123" ssh unitree@192.168.86.21 "tail -50 ~/go2_service.log"

# Look for:
# - WebRTC connection established
# - No repeated connection errors
# - Status should show connected=true
```

### Robot commands not working
- Verify GO2 robot IP is correct: `192.168.86.148`
- Check robot is powered on and connected to same network
- Test status endpoint: `curl http://192.168.86.21:5001/status`

## DO NOT Modify

**Warning:** Do not add watchdog logic, automatic restarts, or complex error recovery to this service. Those features caused the service to fail. Keep it simple and reliable.

If you need advanced features, create a separate experimental version and test thoroughly before deploying to production.

## RTSP Proxy for IR/Depth

To view the IR and depth feeds in the dashboard, run the provided `rtsp_proxy.py` on the Orin. It opens the RTSP streams locally and republishes them as MJPEG over HTTP, which the Mac client can decode reliably.

```
sshpass -p "123" ssh unitree@192.168.1.207
python3 ~/rtsp_proxy.py
```

The proxy listens on `http://192.168.1.207:8600/ir.mjpg` and `.../depth.mjpg`; the web dashboard already points the IR/Depth dropdowns at these endpoints.
