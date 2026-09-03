# GO2 WebRTC Integration into Watch Dog Dashboard - Implementation Plan

## Current Status

### Completed
✅ Standalone GO2 WebRTC control server successfully implemented and tested
✅ Persistent WebRTC connection with battery monitoring
✅ Live video streaming from GO2 camera
✅ All basic commands working (Stand, Crouch, Sit, Hello, Stretch, Wiggle)
✅ Documented implementation ([GO2_WEBRTC_CONTROL.md](GO2_WEBRTC_CONTROL.md))
✅ Standalone server stopped - ready for integration

### To Implement
1. Create GO2 manager module for Watch Dog dashboard
2. Add GO2 battery display to dashboard header
3. Add GO2 WebRTC feed to camera dropdown alongside RTSP feeds
4. Integrate GO2 commands (will discuss after basic integration)

## Integration Architecture

### Proposed Approach: Modular GO2 Manager

Create a new module: `go2_manager.py` that:
- Runs WebRTC connection in background thread
- Provides simple API for main dashboard
- Handles battery monitoring
- Provides video frames
- Manages command queue

### Why Modular Approach?
- **Isolation**: GO2 WebRTC logic separate from main dashboard code
- **Clean**: Minimal changes to existing `web_app.py`
- **Maintainable**: Easy to update GO2 features independently
- **Testable**: Can test GO2 module separately

## File Structure

```
watch_dog/
├── web_app.py                    # Main dashboard (minimal changes)
├── go2_manager.py                # NEW: GO2 WebRTC manager
├── camera.py                     # Update to support GO2 camera
├── templates/
│   └── index.html                # Update: Add battery + GO2 in dropdown
└── GO2_WEBRTC_CONTROL.md         # Existing documentation
```

## Implementation Steps

### Step 1: Create go2_manager.py Module

Features:
- Background thread with persistent WebRTC connection
- LOW_STATE subscription for battery data
- Video frame capture from WebRTC
- Thread-safe API:
  - `get_battery()` → returns {soc, voltage, current}
  - `get_frame()` → returns latest video frame
  - `send_command(cmd)` → sends command to robot
  - `is_connected()` → connection status

Dependencies needed on local machine:
```bash
pip install opencv-python
# Note: unitree_webrtc_connect is already installed on ORIN host (192.168.86.21)
```

### Step 2: Update camera.py

Add GO2 as a camera source:
- Type: "go2_webrtc"
- Source: Uses go2_manager for frames instead of OpenCV VideoCapture
- Special handling for WebRTC frame retrieval

### Step 3: Update web_app.py

Minimal changes:
1. Import go2_manager
2. Initialize GO2 connection at startup
3. Add `/go2/battery` endpoint
4. Camera manager already handles frame routing

### Step 4: Update templates/index.html

Two subtle additions:
1. **Header**: Add battery indicator (small, unobtrusive):
   ```html
   <div class="go2-battery">🐕 <span id="battery">--</span>%</div>
   ```

2. **Camera Dropdown**: Add GO2 option:
   ```html
   <option value="go2_webrtc">GO2 Robot Camera</option>
   ```

### Step 5: Test Integration

1. Start dashboard: `python web_app.py`
2. Verify battery appears in header
3. Select "GO2 Robot Camera" from dropdown
4. Verify GO2 video feed displays
5. (Later) Test command integration

## Configuration

### config.yaml Addition
```yaml
go2:
  enabled: true
  robot_ip: "192.168.86.148"
  connection_method: "LocalSTA"
```

## Network Architecture

```
┌─────────────────────────┐
│  Your Browser           │
│  (localhost:5000)       │
└────────────┬────────────┘
             │ HTTP/WebSocket
             ▼
┌─────────────────────────┐
│  Watch Dog Dashboard    │
│  Mac (localhost)        │
│  - Flask Server         │
│  - GO2 Manager Module   │
└────────────┬────────────┘
             │ SSH to ORIN
             │ WebRTC calls
             ▼
┌─────────────────────────┐
│  ORIN Host              │
│  192.168.86.21          │
│  - GO2 Manager runs     │
│    WebRTC here          │
└────────────┬────────────┘
             │ WebRTC
             │ (WiFi)
             ▼
┌─────────────────────────┐
│  GO2 Robot              │
│  192.168.86.148         │
│  - Camera Stream        │
│  - Battery/LOW_STATE    │
│  - Command Receiver     │
└─────────────────────────┘
```

## Important Notes

### Library Location
- **unitree_webrtc_connect** is installed on ORIN host (192.168.86.21)
- GO2 Manager must run on ORIN, not local Mac
- Two options:
  1. **Remote execution**: SSH to ORIN and run WebRTC code there
  2. **Module deployment**: Deploy go2_manager.py to ORIN

### Video Streaming Approach
Since WebRTC library is on ORIN:
- GO2 Manager runs on ORIN
- Captures frames from WebRTC
- Serves frames via HTTP endpoint
- Dashboard fetches frames from ORIN endpoint

## Recommended Next Step

**Option A: Simple Integration (Faster)**
- Deploy GO2 Manager to ORIN as standalone service
- Dashboard makes HTTP requests to ORIN for frames/battery
- No complex library dependencies on Mac

**Option B: Full Integration (Cleaner)**
- Install unitree_webrtc_connect on Mac
- GO2 Manager runs locally with dashboard
- Direct WebRTC connection from Mac to robot

**Recommendation**: Start with Option A for faster results, then optionally migrate to Option B.

## Questions to Resolve

1. **Battery Display Location**: Where exactly in the header? Top-right corner? Next to other stats?

2. **Camera Name**: What should GO2 camera be called in dropdown?
   - "GO2 Robot Camera"
   - "Mobile Dog Camera"
   - "Unitree GO2"
   - Other?

3. **Commands**: After basic integration, which commands do you want accessible?
   - Quick actions in dashboard?
   - Separate control panel?
   - Context menu on video feed?

## Ready to Proceed?

We have successfully:
- ✅ Tested WebRTC with GO2 (working!)
- ✅ Implemented battery monitoring (working!)
- ✅ Implemented video streaming (working!)
- ✅ Created documentation
- ✅ Committed code to git

Next: Create `go2_manager.py` module and integrate into dashboard.

Shall we proceed with Option A (faster) or Option B (cleaner)?
