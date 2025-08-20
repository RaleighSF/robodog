#!/usr/bin/env python3
from flask import Flask, render_template, Response, jsonify, request
import threading
import time
import cv2
import numpy as np

app = Flask(__name__)

class SimpleWebApp:
    def __init__(self):
        self.is_running = False
        self.camera_source = "mac"
        self.current_frame = None
        self.cap = None
        
    def generate_frames(self):
        """Simple camera capture without object detection"""
        while True:
            if self.is_running and self.cap:
                ret, frame = self.cap.read()
                if ret:
                    # Just return the raw frame without detection
                    ret, buffer = cv2.imencode('.jpg', frame)
                    if ret:
                        frame_bytes = buffer.tobytes()
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            else:
                # Generate test pattern
                test_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(test_frame, "Camera Off", (200, 240), 
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                ret, buffer = cv2.imencode('.jpg', test_frame)
                if ret:
                    frame_bytes = buffer.tobytes()
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            time.sleep(1/15)  # 15 FPS

web_app = SimpleWebApp()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    return Response(web_app.generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/start_detection', methods=['POST'])
def start_detection():
    try:
        # Try to start camera
        web_app.cap = cv2.VideoCapture(0)
        if web_app.cap.isOpened():
            web_app.is_running = True
            return jsonify({'status': 'success', 'message': 'Camera started'})
        else:
            return jsonify({'status': 'error', 'message': 'Camera not available'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/stop_detection', methods=['POST'])
def stop_detection():
    web_app.is_running = False
    if web_app.cap:
        web_app.cap.release()
        web_app.cap = None
    return jsonify({'status': 'success', 'message': 'Camera stopped'})

@app.route('/switch_model', methods=['POST'])
def switch_model():
    model_name = request.json.get('model', 'YOLO')
    return jsonify({'status': 'success', 'message': f'Model switched to {model_name} (simplified mode)'})

@app.route('/switch_camera', methods=['POST'])
def switch_camera():
    data = request.json
    camera_source = data.get('source', 'mac')
    web_app.camera_source = camera_source
    return jsonify({'status': 'success', 'message': f'Camera source: {camera_source} (simplified mode)'})

@app.route('/robot_command', methods=['POST'])
def robot_command():
    return jsonify({'status': 'success', 'message': 'Robot command sent (test mode)'})

@app.route('/status')
def get_status():
    return jsonify({
        'is_running': web_app.is_running,
        'camera_available': web_app.cap is not None and web_app.cap.isOpened() if web_app.cap else False,
        'current_model': 'Simple Camera',
        'camera_status': {'source': web_app.camera_source, 'test_mode': True}
    })

if __name__ == '__main__':
    print("Starting Simplified NTT DATA Project Watch Dog")
    print("Open your browser and go to: http://127.0.0.1:5000")
    print("This version bypasses YOLO detection for testing")
    app.run(debug=True, host='127.0.0.1', port=5000, threaded=True)