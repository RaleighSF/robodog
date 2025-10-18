# 🐕 iDog Local Dashboard

A laptop-based dashboard that connects to and displays RTSP camera streams from the Jetson ORIN on your robot dog.

## 🎯 Quick Start

### 1. Start the Local Dashboard

```bash
# In your development directory
python3 local_camera_dashboard.py
```

### 2. Access the Dashboard

Open your browser and go to: **http://localhost:5002**

### 3. Connect to Camera Streams

Click "🚀 Connect All Cameras" or use individual camera controls to connect to the RTSP streams on your dog.

## 🏗️ How It Works

```
Your Laptop (Dashboard)          Robot Dog (Jetson ORIN)
┌─────────────────────┐          ┌─────────────────────────┐
│  Local Dashboard    │  RTSP    │  Camera Hardware        │
│  localhost:5002     │ ◄─────── │  /dev/video4, etc.      │
│                     │          │                         │
│  • Web Interface    │          │  RTSP Server            │
│  • Stream Display   │          │  192.168.86.21:8554     │
│  • Camera Controls  │          │  • /test                │
└─────────────────────┘          │  • /main                │
                                 │  • /secondary           │
                                 └─────────────────────────┘
```

## 📹 Configured Camera Streams

The dashboard is pre-configured to connect to these RTSP streams on your dog:

1. **Dog Main Camera**
   - URL: `rtsp://192.168.86.21:8554/test`
   - Description: Primary camera feed from Jetson ORIN
   - ✅ This matches your working stream!

2. **Dog RealSense Camera**
   - URL: `rtsp://192.168.86.21:8554/main`
   - Description: RealSense color camera

3. **Dog Secondary Camera**
   - URL: `rtsp://192.168.86.21:8554/secondary`
   - Description: Secondary camera view

## 🎛️ Dashboard Features

### Real-time Status Monitoring
- 🟢 Connection status to the dog
- 📊 Active stream count
- 📹 Camera availability indicators

### Individual Camera Controls
- **Connect Stream** - Start receiving RTSP stream
- **Disconnect** - Stop receiving stream
- **Status Indicators** - Visual connection status
- **Click-to-copy RTSP URLs**

### Global Controls
- **🚀 Connect All Cameras** - Start all available streams
- **🛑 Disconnect All** - Stop all streams
- **🔄 Refresh Status** - Update connection status

### Live Video Display
- Real-time video feeds from the dog
- Automatic reconnection handling
- Frame rate and connection info overlays
- Placeholder displays for disconnected streams

## 🔧 Configuration

To add or modify camera streams, edit the `REMOTE_CAMERAS` dictionary in `local_camera_dashboard.py`:

```python
REMOTE_CAMERAS = {
    "my_new_camera": {
        "name": "My New Camera",
        "rtsp_url": "rtsp://192.168.86.21:8554/my_stream",
        "description": "Description of the camera",
        "status": "unknown"
    }
}
```

## 🌐 API Endpoints

The dashboard provides a REST API for integration:

- `GET /api/cameras` - Get all camera status
- `POST /api/start_stream/<camera_id>` - Start a specific stream
- `POST /api/stop_stream/<camera_id>` - Stop a specific stream
- `GET /api/system_status` - Get system status

## 🎥 Video Feed Endpoints

- `GET /video_feed/<camera_id>` - MJPEG stream for web display
- `GET /` - Main dashboard interface

## 🔍 Troubleshooting

### Dashboard Won't Start
```bash
# Check if port 5002 is available
netstat -an | grep 5002

# Install dependencies
pip3 install opencv-python flask numpy
```

### Can't Connect to Dog Streams
```bash
# Test RTSP stream directly
vlc rtsp://192.168.86.21:8554/test

# Check network connectivity
ping 192.168.86.21

# Verify RTSP server is running on dog
telnet 192.168.86.21 8554
```

### Video Not Displaying
- Check browser console for errors
- Verify camera stream is actually working with VLC
- Try refreshing the page
- Check if the RTSP stream URL is correct

### Performance Issues
- Reduce number of simultaneous streams
- Check network bandwidth
- Monitor CPU usage on laptop

## 🚀 Usage Tips

### Best Performance
1. **Start one camera at a time** to avoid overwhelming the network
2. **Use ethernet connection** for best quality
3. **Close unused streams** to save bandwidth

### Testing Streams
1. **Test with VLC first**: `vlc rtsp://192.168.86.21:8554/test`
2. **Check RTSP server status** on the dog
3. **Verify network connectivity** between laptop and dog

### Multiple Windows
You can open multiple browser tabs to monitor different aspects:
- Main dashboard for camera controls
- Individual video feeds in separate tabs
- API monitoring with developer tools

## 📱 Mobile Access

The dashboard is mobile-responsive. You can access it from your phone by:
1. Finding your laptop's IP address: `ipconfig` (Windows) or `ifconfig` (Mac/Linux)
2. Accessing: `http://YOUR_LAPTOP_IP:5002`

## 🔐 Security Notes

- **Local Network Only** - Dashboard runs on localhost by default
- **No Authentication** - Open access on local network
- **RTSP Streams** - No encryption (standard for RTSP)

## 🎯 Perfect for Your Use Case

Since you already have `rtsp://192.168.86.21:8554/test` working, the dashboard will immediately connect to it and display the video feed with professional controls and monitoring.

---

**🐕 Ready to monitor your robot dog cameras from your laptop!**