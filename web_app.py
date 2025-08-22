#!/usr/bin/env python3
import cv2
import time
import os
from flask import Flask, render_template, Response, jsonify, request, send_file
from hybrid_detector import HybridDetector
from camera import CameraManager
from detection_logger import DetectionLogger

app = Flask(__name__)
camera_manager = CameraManager()
detector = HybridDetector()
detection_logger = DetectionLogger()

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
                    
                    # Log detections (with cooldown logic)
                    logged = detection_logger.log_detections(frame, detections)
                    
                    # Update camera source in the last log entry if a new log was created
                    if logged and detection_logger.detection_logs:
                        detection_logger.detection_logs[-1]['camera_source'] = camera_manager.camera_source
                    
                    # Draw detections on frame
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

@app.route('/switch_camera', methods=['POST'])
def switch_camera():
    """Switch camera source"""
    data = request.json
    camera_source = data.get('source', 'mac')
    robot_ip = data.get('robot_ip', '192.168.12.1')
    
    print(f"Switch camera request: source={camera_source}, ip={robot_ip}")
    
    try:
        camera_manager.set_camera_source(camera_source, robot_ip)
        print(f"Camera source switched. Unitree client: {camera_manager.unitree_client is not None}")
        return jsonify({'status': 'success', 'message': f'Switched to {camera_source} camera'})
    except Exception as e:
        print(f"Error switching camera: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/robot_command', methods=['POST'])
def robot_command():
    """Send command to robot"""
    data = request.json
    command = data.get('command', '')
    params = data.get('params', {})
    
    print(f"Robot command received: {command}")
    print(f"Camera source: {camera_manager.camera_source}")
    print(f"Unitree client exists: {camera_manager.unitree_client is not None}")
    
    if camera_manager.unitree_client:
        print(f"Unitree client connected: {camera_manager.unitree_client.is_connected}")
        result = camera_manager.unitree_client.send_command(command, params)
        print(f"Command result: {result}")
        return jsonify(result)
    else:
        print("No unitree client available")
        return jsonify({'status': 'error', 'message': 'Robot not connected - no client initialized'})

@app.route('/status')
def get_status():
    """Get current status"""
    camera_status = camera_manager.get_camera_status()
    return jsonify({
        'is_running': web_app.is_running,
        'camera_available': camera_manager.is_camera_available(),
        'camera_status': camera_status
    })

@app.route('/detection_logs')
def get_detection_logs():
    """Get detection logs and statistics"""
    try:
        logs = detection_logger.get_recent_logs(limit=50)  # Get last 50 logs
        stats = detection_logger.get_stats()
        return jsonify({
            'status': 'success',
            'logs': logs,
            'stats': stats
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e),
            'logs': [],
            'stats': {}
        })

@app.route('/clear_detection_logs', methods=['POST'])
def clear_detection_logs():
    """Clear all detection logs"""
    try:
        detection_logger.clear_logs()
        return jsonify({
            'status': 'success',
            'message': 'Detection logs cleared successfully'
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        })

@app.route('/thumbnail/<filename>')
def serve_thumbnail(filename):
    """Serve thumbnail images"""
    try:
        thumbnail_path = os.path.join(detection_logger.log_dir, "thumbnails", filename)
        if os.path.exists(thumbnail_path):
            return send_file(thumbnail_path, mimetype='image/jpeg')
        else:
            return jsonify({'error': 'Thumbnail not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/image/<filename>')
def serve_large_image(filename):
    """Serve larger images for modal display, fallback to thumbnail if needed"""
    try:
        # Try to serve the large image first
        image_path = os.path.join(detection_logger.log_dir, "images", filename)
        if os.path.exists(image_path):
            return send_file(image_path, mimetype='image/jpeg')
        
        # Fallback to thumbnail for older entries (will be upscaled by CSS)
        thumbnail_path = os.path.join(detection_logger.log_dir, "thumbnails", filename)
        if os.path.exists(thumbnail_path):
            return send_file(thumbnail_path, mimetype='image/jpeg')
        
        return jsonify({'error': 'Image not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    print("Starting Computer Vision Object Detector Web App")
    print("Open your browser and go to: http://127.0.0.1:5000")
    app.run(debug=True, host='127.0.0.1', port=5000, threaded=True)