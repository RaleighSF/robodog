# GO2 Dashboard Integration - Ready to Complete

## Status: GO2 Service Running ✅

The GO2 service is now operational on the ORIN host and ready for dashboard integration!

### Service Endpoints (LIVE NOW):
- **Battery**: http://192.168.86.21:5001/battery
- **Video Feed**: http://192.168.86.21:5001/video_feed
- **Status**: http://192.168.86.21:5001/status

Test them! Open in browser to verify they work.

## What's Been Accomplished

✅ Standalone GO2 WebRTC implementation (fully working)
✅ Persistent WebRTC connection with optimized performance
✅ Real-time battery monitoring via LOW_STATE subscription
✅ Live video streaming from GO2 camera
✅ All basic commands tested and working
✅ **GO2 Service deployed to ORIN host** (running on port 5001)
✅ Documentation created ([GO2_WEBRTC_CONTROL.md](GO2_WEBRTC_CONTROL.md))
✅ Git commit created with all work

## Architecture

```
Watch Dog Dashboard (localhost:5000)
        │
        │ HTTP requests for battery/video
        ▼
GO2 Service (192.168.86.21:5001) ◄── WebRTC ──► GO2 Robot (192.168.86.148)
```

**Most Reliable & Responsive Solution** (as requested):
- GO2 Service runs on ORIN where WebRTC library is installed
- Dashboard makes simple HTTP requests (no complex dependencies)
- Proven working implementation
- Fast and stable

## Next Steps to Complete Integration

### Step 1: Update config.yaml

Add GO2 configuration:

```yaml
go2:
  enabled: true
  service_url: "http://192.168.86.21:5001"
```

### Step 2: Add GO2 as Camera Source

Edit `camera.py` - Add new camera type:

```python
# In CameraManager class, add GO2 support
def add_camera(self, source, name=None):
    if source == "go2":
        # Special handling for GO2 - uses service endpoint instead of OpenCV
        self.camera_sources[name or "Native Go2 Camera"] = {
            'type': 'go2_webrtc',
            'url': 'http://192.168.86.21:5001/video_feed'
        }
    else:
        # Existing RTSP/camera code...
```

### Step 3: Update Camera Frame Retrieval

In `camera.py`, modify frame retrieval to support HTTP streams:

```python
def get_frame(self):
    camera_info = self.camera_sources.get(self.current_camera)
    if camera_info and camera_info.get('type') == 'go2_webrtc':
        # Fetch frame from GO2 service HTTP endpoint
        import requests
        resp = requests.get(camera_info['url'], stream=True, timeout=1)
        # Parse MJPEG stream...
        return frame
    else:
        # Existing OpenCV code...
```

### Step 4: Add Battery Display to Dashboard

Edit `templates/index.html` - Find the video overlay badge (the one that says "Camera Feed"), add battery percentage to it:

```html
<!-- Existing badge, modify to include battery -->
<div class="camera-badge">
    <span id="camera-name">Camera Feed</span>
    <span id="go2-battery" style="margin-left: 10px; display:none;">
        🔋 <span id="battery-percent">--</span>%
    </span>
</div>
```

### Step 5: Add Battery Update JavaScript

In `templates/index.html`, add JavaScript to fetch battery:

```javascript
// Add to existing JavaScript
function updateGO2Battery() {
    fetch('http://192.168.86.21:5001/battery')
        .then(r => r.json())
        .then(data => {
            if (data.soc !== null) {
                document.getElementById('battery-percent').textContent = data.soc;
                document.getElementById('go2-battery').style.display = 'inline';
            }
        })
        .catch(e => {
            // GO2 not available, hide battery
            document.getElementById('go2-battery').style.display = 'none';
        });
}

// Call every 3 seconds
setInterval(updateGO2Battery, 3000);
updateGO2Battery(); // Initial call
```

### Step 6: Add "Native Go2 Camera" to Dropdown

In `web_app.py`, find where camera sources are populated for the dropdown, add:

```python
# Add GO2 camera to available sources
camera_sources = camera_manager.get_available_cameras()
camera_sources.append("Native Go2 Camera")  # or add via camera_manager.add_camera("go2", "Native Go2 Camera")
```

### Step 7: Test the Integration

1. Start GO2 service on ORIN (already running!)
2. Start Watch Dog dashboard: `python web_app.py`
3. Open dashboard in browser
4. Select "Native Go2 Camera" from dropdown
5. Verify:
   - ✅ GO2 video feed displays
   - ✅ Battery percentage appears in video overlay badge
   - ✅ Battery updates every 3 seconds

## File Locations

### On ORIN Host (192.168.86.21):
- `~/go2_service.py` - GO2 Service (running on port 5001)
- `~/go2_webrtc_connect_2x/` - WebRTC library installation

### In Watch Dog Project:
- `web_app.py` - Main dashboard (minimal changes needed)
- `camera.py` - Camera manager (add GO2 support)
- `templates/index.html` - Dashboard UI (add battery + dropdown option)
- `config.yaml` - Configuration (add GO2 settings)

## Commands (For Later Discussion)

Once basic integration is complete, we can discuss adding GO2 commands to the dashboard:
- Stand Up / Crouch / Sit
- Hello Wave / Stretch / Wiggle
- Movement controls

Options for command UI:
- Buttons in sidebar
- Context menu on video
- Separate control panel

## Keeping GO2 Service Running

To keep the GO2 service running persistently on ORIN:

```bash
# SSH to ORIN
ssh unitree@192.168.86.21

# Create systemd service (optional but recommended)
sudo nano /etc/systemd/system/go2-service.service
```

Service file content:
```ini
[Unit]
Description=GO2 WebRTC Service for Watch Dog Dashboard
After=network.target

[Service]
Type=simple
User=unitree
WorkingDirectory=/home/unitree
ExecStart=/usr/bin/python3 /home/unitree/go2_service.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable go2-service
sudo systemctl start go2-service
sudo systemctl status go2-service
```

## Quick Integration Summary

**What You Need to Do:**
1. Update 3 files in Watch Dog project:
   - `camera.py` - Add GO2 as camera source
   - `templates/index.html` - Add battery to badge + dropdown option
   - `config.yaml` - Add GO2 config

2. Restart Watch Dog dashboard

3. Select "Native Go2 Camera" from dropdown

**Estimated Time:** 15-20 minutes of coding

## Testing Checklist

- [ ] GO2 service accessible at http://192.168.86.21:5001/status
- [ ] Battery endpoint returns data: http://192.168.86.21:5001/battery
- [ ] Video feed loads: http://192.168.86.21:5001/video_feed
- [ ] "Native Go2 Camera" appears in dashboard dropdown
- [ ] Selecting GO2 camera shows live video
- [ ] Battery percentage appears in video overlay badge
- [ ] Battery updates automatically

## Troubleshooting

**If GO2 service isn't running:**
```bash
ssh unitree@192.168.86.21
python3 ~/go2_service.py
```

**If video doesn't load:**
- Check GO2 service logs
- Verify robot is powered on and connected to WiFi
- Test video URL directly in browser

**If battery doesn't update:**
- Check browser console for CORS errors
- Verify battery endpoint returns valid JSON
- Check JavaScript console for errors

## Ready to Proceed!

The hard work is done - the GO2 service is running and proven to work. The remaining integration is straightforward HTTP requests and UI updates.

Would you like me to create the specific code changes for the 3 files? Or would you prefer to implement them yourself based on this guide?
