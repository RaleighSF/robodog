#!/usr/bin/env python3
"""
🐕 iDog Local Camera Dashboard
Runs on your laptop and displays RTSP streams from the Jetson ORIN on the dog
"""
import cv2
import numpy as np
import threading
import time
import json
from flask import Flask, render_template, Response, jsonify, request

# Configuration - Jetson ORIN on the dog
JETSON_IP = "192.168.86.21"
RTSP_PORT = 8554
WEB_PORT = 5002  # Different port to avoid conflict with main web_app

# Remote camera configurations (streams from the dog)
REMOTE_CAMERAS = {
    "dog_main": {
        "name": "Dog Main Camera",
        "rtsp_url": f"rtsp://{JETSON_IP}:{RTSP_PORT}/test",
        "description": "Primary camera feed from Jetson ORIN",
        "status": "unknown"
    },
    "dog_realsense": {
        "name": "Dog RealSense Camera", 
        "rtsp_url": f"rtsp://{JETSON_IP}:{RTSP_PORT}/main",
        "description": "RealSense color camera",
        "status": "unknown"
    },
    "dog_secondary": {
        "name": "Dog Secondary Camera",
        "rtsp_url": f"rtsp://{JETSON_IP}:{RTSP_PORT}/secondary", 
        "description": "Secondary camera view",
        "status": "unknown"
    }
}

class RTSPStreamManager:
    """Manage RTSP streams from remote cameras"""
    
    def __init__(self):
        self.streams = {}
        self.stream_threads = {}
        self.latest_frames = {}
        self.connection_status = {}
        
    def start_stream(self, camera_id, rtsp_url):
        """Start capturing from RTSP stream"""
        if camera_id in self.stream_threads:
            self.stop_stream(camera_id)
            
        self.connection_status[camera_id] = "connecting"
        
        # Start stream thread
        thread = threading.Thread(
            target=self._stream_worker, 
            args=(camera_id, rtsp_url),
            daemon=True
        )
        thread.start()
        self.stream_threads[camera_id] = thread
        
    def stop_stream(self, camera_id):
        """Stop RTSP stream"""
        if camera_id in self.streams:
            # Signal thread to stop
            self.connection_status[camera_id] = "stopping"
            
            # Wait a bit for graceful shutdown
            time.sleep(0.5)
            
            # Clean up
            if camera_id in self.streams:
                del self.streams[camera_id]
            if camera_id in self.latest_frames:
                del self.latest_frames[camera_id]
            if camera_id in self.stream_threads:
                del self.stream_threads[camera_id]
                
        self.connection_status[camera_id] = "stopped"
    
    def _stream_worker(self, camera_id, rtsp_url):
        """Worker thread to capture RTSP stream"""
        print(f"🔗 Connecting to {camera_id}: {rtsp_url}")
        
        # Try to connect to RTSP stream
        cap = cv2.VideoCapture(rtsp_url)
        
        # Set buffer size to reduce latency
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        
        if not cap.isOpened():
            print(f"❌ Failed to connect to {camera_id}")
            self.connection_status[camera_id] = "failed"
            return
            
        print(f"✅ Connected to {camera_id}")
        self.connection_status[camera_id] = "connected"
        self.streams[camera_id] = cap
        
        # Stream capture loop
        frame_count = 0
        while self.connection_status.get(camera_id) not in ["stopping", "stopped"]:
            ret, frame = cap.read()
            
            if not ret:
                print(f"⚠️ Lost connection to {camera_id}")
                self.connection_status[camera_id] = "disconnected"
                break
                
            # Add overlay with stream info
            frame_count += 1
            timestamp = time.strftime("%H:%M:%S")
            
            # Add info overlay
            overlay_text = f"{REMOTE_CAMERAS[camera_id]['name']} | {timestamp} | Frame {frame_count}"
            cv2.putText(frame, overlay_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            
            # Add connection indicator
            status_color = (0, 255, 0) if self.connection_status[camera_id] == "connected" else (0, 0, 255)
            cv2.circle(frame, (frame.shape[1] - 30, 30), 10, status_color, -1)
            
            # Store latest frame
            self.latest_frames[camera_id] = frame.copy()
            
            # Small delay to prevent overwhelming
            time.sleep(0.03)  # ~30 FPS max
        
        # Cleanup
        cap.release()
        print(f"🛑 Stream worker stopped for {camera_id}")
    
    def get_mjpeg_stream(self, camera_id):
        """Generate MJPEG stream for web display"""
        while True:
            if camera_id in self.latest_frames:
                frame = self.latest_frames[camera_id]
                
                # Encode frame as JPEG
                ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ret:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            else:
                # Generate placeholder frame
                placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
                status = self.connection_status.get(camera_id, "unknown")
                
                # Add status text
                status_text = f"Camera: {camera_id}"
                status_line2 = f"Status: {status.upper()}"
                if status == "failed":
                    status_line3 = "Check RTSP stream on dog"
                elif status == "connecting":
                    status_line3 = "Connecting to stream..."
                else:
                    status_line3 = "No video data"
                
                cv2.putText(placeholder, status_text, (50, 200), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
                cv2.putText(placeholder, status_line2, (50, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 0), 2)  
                cv2.putText(placeholder, status_line3, (50, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)
                
                ret, buffer = cv2.imencode('.jpg', placeholder)
                if ret:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            
            time.sleep(0.1)  # 10 FPS for web display

# Flask Web Application
app = Flask(__name__)
stream_manager = RTSPStreamManager()

@app.route('/')
def index():
    """Main dashboard"""
    return render_template('local_dashboard.html', 
                         cameras=REMOTE_CAMERAS, 
                         jetson_ip=JETSON_IP, 
                         rtsp_port=RTSP_PORT)

@app.route('/video_feed/<camera_id>')
def video_feed(camera_id):
    """Video streaming route for MJPEG"""
    return Response(stream_manager.get_mjpeg_stream(camera_id),
                   mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/cameras')
def list_cameras():
    """Get camera status"""
    camera_status = {}
    for camera_id, camera_config in REMOTE_CAMERAS.items():
        status = stream_manager.connection_status.get(camera_id, "stopped")
        camera_status[camera_id] = {
            "name": camera_config["name"],
            "rtsp_url": camera_config["rtsp_url"],
            "description": camera_config["description"],
            "status": status,
            "has_video": camera_id in stream_manager.latest_frames
        }
    return jsonify(camera_status)

@app.route('/api/start_stream/<camera_id>', methods=['POST'])
def start_stream(camera_id):
    """Start RTSP stream"""
    if camera_id in REMOTE_CAMERAS:
        rtsp_url = REMOTE_CAMERAS[camera_id]["rtsp_url"]
        stream_manager.start_stream(camera_id, rtsp_url)
        return jsonify({"success": True, "camera_id": camera_id})
    return jsonify({"success": False, "error": "Camera not found"})

@app.route('/api/stop_stream/<camera_id>', methods=['POST'])
def stop_stream(camera_id):
    """Stop RTSP stream"""
    stream_manager.stop_stream(camera_id)
    return jsonify({"success": True, "camera_id": camera_id})

@app.route('/api/system_status')
def system_status():
    """Get system status"""
    active_streams = len([c for c in stream_manager.connection_status.values() if c == "connected"])
    
    return jsonify({
        "jetson_ip": JETSON_IP,
        "rtsp_port": RTSP_PORT,
        "active_streams": active_streams,
        "available_cameras": len(REMOTE_CAMERAS),
        "connection_status": stream_manager.connection_status
    })

def cleanup():
    """Cleanup function"""
    print("\n🛑 Shutting down local dashboard...")
    for camera_id in list(stream_manager.streams.keys()):
        stream_manager.stop_stream(camera_id)

if __name__ == '__main__':
    import atexit
    import signal
    
    atexit.register(cleanup)
    signal.signal(signal.SIGINT, lambda s, f: cleanup())
    
    print("🐕 iDog Local Camera Dashboard Starting...")
    print("=" * 50)
    print(f"📱 Local Dashboard: http://localhost:{WEB_PORT}")
    print(f"🐕 Dog RTSP Server: rtsp://{JETSON_IP}:{RTSP_PORT}")
    print("=" * 50)
    
    print(f"\n🔗 Configured Remote Streams:")
    for camera_id, config in REMOTE_CAMERAS.items():
        print(f"   {config['name']:20} {config['rtsp_url']}")
    
    print(f"\n🚀 Starting local web server on port {WEB_PORT}...")
    
    try:
        app.run(host='localhost', port=WEB_PORT, debug=False, threaded=True)
    except KeyboardInterrupt:
        cleanup()