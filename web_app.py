#!/usr/bin/env python3
import cv2
import numpy as np
import base64
import json
import threading
import time
from flask import Flask, render_template, Response, jsonify, request
from hybrid_detector import HybridDetector
from camera import CameraManager

app = Flask(__name__)
camera_manager = CameraManager()
detector = HybridDetector()

class WebApp:
    def __init__(self):
        self.is_running = False
        self.current_frame = None
        
    def generate_frames(self):
        """Generate video frames for streaming"""
        while True:
            if self.is_running and camera_manager.is_camera_available():
                frame = camera_manager.get_frame()
                if frame is not None:
                    # Perform detection
                    detections = detector.detect(frame)
                    annotated_frame = detector.draw_detections(frame, detections)
                    
                    # Encode frame as JPEG
                    ret, buffer = cv2.imencode('.jpg', annotated_frame)
                    if ret:
                        frame_bytes = buffer.tobytes()
                        yield (b'--frame\r\n'
                               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
            else:
                time.sleep(0.1)

web_app = WebApp()

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    """Video streaming route"""
    return Response(web_app.generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/start_detection', methods=['POST'])
def start_detection():
    """Start object detection"""
    try:
        if camera_manager.start():
            web_app.is_running = True
            return jsonify({'status': 'success', 'message': 'Detection started'})
        else:
            return jsonify({'status': 'error', 'message': 'Failed to start camera'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/stop_detection', methods=['POST'])
def stop_detection():
    """Stop object detection"""
    web_app.is_running = False
    camera_manager.stop()
    return jsonify({'status': 'success', 'message': 'Detection stopped'})

@app.route('/switch_model', methods=['POST'])
def switch_model():
    """Switch detection model"""
    model_name = request.json.get('model', 'YOLO')
    detector.switch_model(model_name)
    return jsonify({'status': 'success', 'message': f'Switched to {model_name}'})

@app.route('/status')
def get_status():
    """Get current status"""
    return jsonify({
        'is_running': web_app.is_running,
        'camera_available': camera_manager.is_camera_available(),
        'current_model': detector.current_model
    })

if __name__ == '__main__':
    print("Starting Computer Vision Object Detector Web App")
    print("Open your browser and go to: http://127.0.0.1:5000")
    app.run(debug=True, host='127.0.0.1', port=5000, threaded=True)