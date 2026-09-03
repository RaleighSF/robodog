# Performance Analysis - Robot Dog Patrol System
**Date**: November 10, 2025
**Analyst**: Claude

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Mac (192.168.50.17)                                            │
│  - Browser accessing dashboard                                   │
│  - Development/editing                                           │
└─────────────────────────────────────────────────────────────────┘
                            │ HTTP/WebSocket
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  AGX Xavier Dashboard (192.168.50.208)                          │
│  - Flask web app (start_web_app.py)                             │
│  - Object detection (YOLO11)                                     │
│  - Video processing & streaming                                  │
│  - CPU: 1.2% baseline, ~1.5 load average                        │
│  - Memory: 1.9GB / 61GB (3% utilization)                        │
└─────────────────────────────────────────────────────────────────┘
                            │ HTTP requests
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  Orin Backpack (192.168.50.207)  [4-core ARM CPU]              │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │  GO2 Service (go2_service.py)                             │ │
│  │  - Connects to GO2 robot                                  │ │
│  │  - WebRTC video passthrough                               │ │
│  │  - Command/battery API                                    │ │
│  │  - CPU: 32% (healthy)                                     │ │
│  └───────────────────────────────────────────────────────────┘ │
│  ┌───────────────────────────────────────────────────────────┐ │
│  │  RTSP Server (rtsp_rs.py)  ⚠️ BOTTLENECK                  │ │
│  │  - RealSense camera capture (Color, IR, Depth)           │ │
│  │  - 3 simultaneous streams @ 15fps                         │ │
│  │  - GStreamer encoding (NVENC for IR/Depth, x264 Color)   │ │
│  │  - CPU: 103% (CRITICALLY HIGH - 258% of one core!)       │ │
│  └───────────────────────────────────────────────────────────┘ │
│  - Total Load: 3.88 average (overloaded on 4 cores!)           │
│  - Memory: 1.5GB / 15GB (10% utilization)                       │
└─────────────────────────────────────────────────────────────────┘
                            │ Direct connection
                            ↓
                      ┌──────────┐
                      │ GO2 Robot│
                      └──────────┘
```

## Performance Bottlenecks

### 🔴 CRITICAL: RTSP Server CPU Overload (Orin)

**Current State:**
- RTSP server consumes **103% CPU** constantly (even with no clients!)
- This is **258% of a single ARM core**
- Total system load: **3.88** on a 4-core CPU (should be <4.0)

**Root Cause:**
The RTSP server runs continuously regardless of client connections:
1. **RealSense Pipeline**: Captures 3 streams at 15fps = 45 total fps
2. **Frame Processing**: Color conversion for IR, colorization for Depth
3. **Video Encoding**:
   - Color stream: x264 CPU encoding (slowest)
   - IR stream: NVENC hardware encoding
   - Depth stream: NVENC hardware encoding
4. **GStreamer Timers**: Each mount point creates persistent timer callbacks

**Impact:**
- When OpenCV tries to connect via RTSP, the server is too busy to respond
- Connection attempts timeout after 30 seconds
- Switching from Native GO2 camera to RTSP feeds takes 30+ seconds

**Why It Happens:**
```python
# Line 170 in rtsp_rs.py - Timer never stops!
GLib.timeout_add(int(1000/self.cfg.fps), push, None)

# Line 54 - Producer runs forever
while True:  # Captures frames constantly
    fs = pc.poll_for_frames()
```

### 🟡 MODERATE: Network Latency

**Measured:** 4-97ms latency (avg 59ms) between Mac and Orin
- Min: 4.5ms (excellent)
- Avg: 59.6ms (acceptable for LAN)
- Max: 97.4ms (occasional spikes)
- StdDev: 39.9ms (high variance indicates WiFi congestion)

**Impact:** Minimal for RTSP, but contributes to perceived sluggishness

### 🟢 GOOD: AGX Xavier Dashboard

**Current State:**
- CPU: **1.2%** baseline (excellent)
- Load: **1.52** average (healthy on 8-core system)
- Memory: **1.9GB / 61GB** (3% - plenty of headroom)

**Optimizations Applied:**
✅ Detection worker shutdown on camera stop ([web_app.py:552-555](web_app.py#L552-L555))
✅ GO2 WebRTC explicit cleanup ([camera.py:328-331](camera.py#L328-L331))
✅ Network binding to 0.0.0.0 ([web_app.py:1189](web_app.py#L1189))

**Result:** Dashboard is well-optimized and not the bottleneck

### 🟢 GOOD: GO2 Service

**Current State:**
- CPU: **32%** (reasonable for WebRTC encoding)
- Running time: 1h 25min (stable)

**Status:** Operating within normal parameters

## Root Cause: RTSP Server Architecture

### Current Design (Flawed)
```python
# Runs continuously, regardless of clients
producer_thread → RealSense @ 15fps → 3 streams
                       ↓
              frames_dict (shared)
                       ↓
              GLib timers @ 15fps → Encode → GStreamer → RTSP
                       ↓
              (103% CPU even with 0 clients!)
```

### Proposed Design (Optimal)
```python
# Only run when clients connected
RTSP client connects → Signal producer thread
                            ↓
              RealSense starts @ 15fps
                            ↓
              Capture → Encode → Stream
                            ↓
RTSP client disconnects → Stop RealSense → CPU drops to ~0%
```

## Attempted Fixes & Results

### ❌ Fix #1: Client Connection Gating (Failed)
**Approach:** Track active clients and only run RealSense when needed
**File:** `/tmp/rtsp_rs_optimized.py`
**Result:** Broke frame delivery - clients connected but received no frames
**Reason:** GStreamer factory lifecycle is complex; client tracking hooks didn't work as expected

### ❌ Fix #2: Reduce FPS from 30 to 15 (Partial)
**Approach:** Lower frame rate to reduce CPU load
**File:** `/tmp/rtsp_rs_simple_fix.py`
**Result:** CPU dropped from 118% to 103%, but still overloaded
**Reason:** Even at 15fps, running 3 streams + encoding continuously is too much

### ✅ Fix #3: AGX Dashboard Optimizations (Success)
**Approach:** Stop detection worker and cleanup cameras properly
**Files:**
- `web_app.py:552-555` - Detection worker shutdown
- `camera.py:328-331` - GO2 WebRTC explicit stop
**Result:** Dashboard CPU remains low, camera switching is clean
**Status:** Working as intended

## Recommendations

### Immediate (Quick Wins)

1. **Use Only One RTSP Stream at a Time**
   - Disable Color and Depth streams
   - Only enable IR stream
   - Expected CPU reduction: 103% → ~40%

2. **Lower Resolution**
   ```python
   IR = Cfg("ir", 640, 360, 15, 1_500_000)  # Down from 848x480
   ```
   - Expected CPU reduction: ~20-30%

3. **Increase RTSP Connection Timeout**
   ```python
   os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;tcp|stimeout;60000000'  # 60s instead of 5s
   ```
   - Gives server more time to respond when busy

### Medium-Term (Proper Fix)

4. **Implement Proper Client Gating**
   - Use GStreamer's `media-configure` signal properly
   - Implement `RTSPMediaFactory.media_constructed` callback
   - Start RealSense only when first client connects
   - Stop RealSense when last client disconnects
   - Expected CPU when idle: ~5%

5. **Profile RealSense Capture**
   ```bash
   python3 -m cProfile -o rtsp_profile.stats rtsp_rs.py
   ```
   - Identify which part of capture/encode is slowest
   - Optimize bottleneck specifically

### Long-Term (Architecture Change)

6. **Separate RTSP Server Process**
   - Run RTSP server in Docker container with CPU limits
   - Use systemd service with CPUQuota=50%
   - Prevents RTSP from starving other services

7. **Use MediaMTX Instead of Custom GStreamer**
   - Pre-built RTSP server with proper client tracking
   - Built-in performance optimizations
   - Lower CPU usage
   ```bash
   # Install MediaMTX
   ./mediamtx &
   # Configure to read from RealSense via FFmpeg
   ```

8. **Hardware Decode on Client Side**
   - Stream raw H.264 without re-encoding
   - Use browser's hardware decoder
   - Reduces Orin CPU by ~50%

## Performance Targets

| Metric | Current | Target | Status |
|--------|---------|--------|--------|
| RTSP Server CPU | 103% | <25% | 🔴 Critical |
| Orin Load Average | 3.88 | <2.0 | 🔴 Critical |
| AGX Dashboard CPU | 1.2% | <5% | ✅ Excellent |
| RTSP Connection Time | 30s | <3s | 🔴 Critical |
| Camera Switch Time | 3-5s | <2s | 🟡 Acceptable |
| GO2 Service CPU | 32% | <40% | ✅ Good |

## Conclusion

**The AGX Xavier dashboard is well-optimized and not the bottleneck.**

**The RTSP server on the Orin is critically overloaded:**
- Running at 103% CPU constantly (even with no clients)
- Causes 30-second connection delays
- Needs architectural changes to implement proper client gating

**Quick Fix Option:** Disable Color and Depth streams, only use IR channel, expect ~60% CPU reduction.

**Proper Fix Required:** Implement GStreamer client lifecycle hooks to start/stop RealSense based on actual client connections.
