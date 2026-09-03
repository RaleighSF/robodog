#!/usr/bin/env python3
import cv2
import time
import os
import atexit
import signal
import queue
from flask import Flask, render_template, Response, jsonify, request, send_file
from hybrid_detector import HybridDetector
from camera import CameraManager
from detection_logger import DetectionLogger
from telemetry_exporter import TelemetryManager, init_telemetry, get_telemetry
from scene_narrator import init_narrator, get_narrator
from gesture_detector import get_gesture_detector
from ppe_detector import get_ppe_detector
from hand_detector import get_hand_detector
import asyncio
import threading
import json
import logging
from datetime import datetime
import requests
from robot_host import robot_host

# Enable more detailed logging for WebRTC debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
camera_manager = CameraManager()
detector = HybridDetector()
detection_logger = DetectionLogger()

# Cleanup function to prevent semaphore leaks
def cleanup_resources():
    """Clean up camera and detector resources"""
    print("🧹 Cleaning up resources...")
    camera_manager.cleanup()
    try:
        if 'web_app' in globals():
            web_app.shutdown_detection_worker()
    except Exception:
        pass
    print("✅ Resource cleanup completed")

# Register cleanup functions
atexit.register(cleanup_resources)

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    print(f"\n📡 Received signal {signum}, shutting down gracefully...")
    cleanup_resources()
    os._exit(0)

# Register signal handlers for graceful shutdown
signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # Termination signal

class WebApp:
    def __init__(self):
        self.is_running = False
        self.current_frame = None
        # Cache config manager to avoid repeated imports
        self._config_manager = None
        # Track active stream to prevent multiple concurrent streams
        self.stream_active = False
        self.stream_generation_id = 0
        # Detection throttling / reuse
        self._detection_lock = threading.Lock()
        self._last_detections = []
        self._last_detection_ts = 0.0
        # Retuned 2026-09-02 for GPU. Was 0.25 (~4 FPS), a CPU-era compromise.
        # YOLO11m @1280 measures ~59 ms on the Orin GPU, so 0.1 s (~10 FPS) leaves
        # roughly 40% headroom for the VLM, JPEG encode and telemetry.
        self._detection_interval = 0.1   # seconds between detector invocations (~10 FPS)
        # Source frames are 1280x720; 1280 means no downscale at all. The old 800 px
        # cap existed only to make CPU inference tractable and cost small-object recall.
        self._max_detection_width = 1280 # native width — no downscale on GPU
        self._last_start_request = 0.0
        self._last_stop_request = 0.0
        self._throttle_window = 3.0  # seconds between successive start/stop calls
        # Asynchronous detection worker
        self._detection_queue = queue.Queue(maxsize=1)
        self._detection_thread = None
        self._detection_stop_event = threading.Event()
        self._last_detection_enqueue_ts = 0.0
        self._last_detection_frame_size = (0, 0)
        self._feeder_thread = None
        self._feeder_stop_event = threading.Event()
        # Stream exit signaling
        self._stream_exited = threading.Event()
        self._stream_exited.set()
        # Telemetry health counters (read by heartbeat)
        self._frames_processed = 0
        self._detection_fps = 0.0
        self._det_fps_ts = time.time()
        self._det_fps_count = 0
        # Detection pause
        self._detection_paused = False
        # Alert log cooldown — suppress duplicate log entries for 10 seconds
        self._last_alert_log_ts = 0.0
        self._alert_log_cooldown = 10.0  # seconds
        # Cached battery/robot state for telemetry (refreshed by heartbeat)
        self._cached_robot_state = {
            'soc': None, 'voltage': None,
            'current': None, 'connected': False,
            'motion_mode': 'normal',
        }

    def _ensure_detection_worker(self):
        """Make sure the background detection worker is running."""
        if self._detection_thread and self._detection_thread.is_alive():
            return
        self._detection_stop_event.clear()
        # Drain the queue before starting a new worker.
        #
        # shutdown_detection_worker() enqueues a None sentinel to wake the worker,
        # but the worker's loop tests _detection_stop_event FIRST, so it usually
        # exits without ever consuming that sentinel. The None then survives in the
        # queue, and the next worker's first get() returns it and breaks out
        # immediately - leaving NO worker running while is_running stays True.
        # The visible symptom is detections frozen at their last value forever.
        drained = 0
        while True:
            try:
                self._detection_queue.get_nowait()
                self._detection_queue.task_done()
                drained += 1
            except queue.Empty:
                break
        if drained:
            logger.info("[DetectionWorker] drained %d stale queue item(s) before start", drained)
        self._detection_thread = threading.Thread(
            target=self._detection_worker_loop,
            name="DetectionWorker",
            daemon=True
        )
        self._detection_thread.start()

    def _start_detection_feeder(self):
        """Continuously enqueue frames for detection regardless of video feed usage."""
        if self._feeder_thread and self._feeder_thread.is_alive():
            return
        self._feeder_stop_event.clear()
        self._feeder_thread = threading.Thread(
            target=self._detection_feeder_loop,
            name="DetectionFeeder",
            daemon=True
        )
        self._feeder_thread.start()

    def _stop_detection_feeder(self):
        self._feeder_stop_event.set()
        if self._feeder_thread:
            self._feeder_thread.join(timeout=1.0)
            self._feeder_thread = None

    def _detection_feeder_loop(self):
        frame_count = 0
        none_frame_count = 0
        loop_iterations = 0
        print(f"[DetectionFeeder] Starting feeder loop...")
        while not self._feeder_stop_event.is_set():
            loop_iterations += 1
            if loop_iterations <= 5:  # Log first 5 iterations for debugging
                print(f"[DetectionFeeder] Iteration {loop_iterations}: is_running={self.is_running}, camera_available={camera_manager.is_camera_available()}")

            if self.is_running and camera_manager.is_camera_available():
                frame = camera_manager.get_frame()
                if frame is not None:
                    now = time.time()
                    if ((now - self._last_detection_enqueue_ts) >= self._detection_interval
                            and not self._detection_queue.full()):
                        try:
                            self._detection_queue.put(frame.copy(), timeout=0.01)
                            self._last_detection_enqueue_ts = now
                            self._last_detection_frame_size = (frame.shape[1], frame.shape[0])
                            frame_count += 1
                            if frame_count == 1 or frame_count % 20 == 0:  # Log first frame and every 20 frames
                                print(f"[DetectionFeeder] Enqueued {frame_count} frames for detection")
                        except queue.Full:
                            pass
                else:
                    none_frame_count += 1
                    if none_frame_count <= 10 or none_frame_count % 100 == 0:  # Log first 10 and every 100
                        print(f"[DetectionFeeder] Frame is None (count: {none_frame_count})")
                    time.sleep(0.01)
            else:
                if loop_iterations <= 5:
                    print(f"[DetectionFeeder] Not running or camera not available, sleeping...")
                time.sleep(0.05)
        print(f"[DetectionFeeder] Exiting - enqueued {frame_count} total frames, got {none_frame_count} None frames, {loop_iterations} iterations")

    def _detection_worker_loop(self):
        """Background worker that runs detection so streaming thread stays responsive."""
        detection_count = 0
        while not self._detection_stop_event.is_set():
            try:
                frame = self._detection_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if frame is None:
                self._detection_queue.task_done()
                break

            # Drain queue — always process the newest frame to reduce lag
            while not self._detection_queue.empty():
                try:
                    newer = self._detection_queue.get_nowait()
                    self._detection_queue.task_done()
                    if newer is None:
                        frame = None
                        break
                    frame = newer
                except queue.Empty:
                    break

            # Check if drain loop received a None sentinel
            if frame is None:
                self._detection_queue.task_done()
                break

            try:
                # Skip detection when paused (queue is still drained above)
                # task_done() is handled by the finally block below
                if self._detection_paused:
                    continue

                if not self._config_manager:
                    from config import get_config
                    self._config_manager = get_config()

                detection_frame = frame
                scale_factor = 1.0
                height, width = frame.shape[:2]
                if width > self._max_detection_width:
                    scale_factor = self._max_detection_width / width
                    new_size = (self._max_detection_width, int(height * scale_factor))
                    detection_frame = cv2.resize(frame, new_size, interpolation=cv2.INTER_AREA)

                detections = detector.detect(detection_frame)

                if detections and scale_factor != 1.0:
                    inv_scale = 1.0 / scale_factor
                    for detection in detections:
                        x, y, w, h = detection.bbox
                        detection.bbox = (
                            int(x * inv_scale),
                            int(y * inv_scale),
                            int(w * inv_scale),
                            int(h * inv_scale),
                        )

                with self._detection_lock:
                    self._last_detections = detections
                    self._last_detection_ts = time.time()
                    self._last_detection_frame_size = (frame.shape[1], frame.shape[0])
                detection_count += 1
                self._frames_processed += 1
                # Update rolling FPS (recalc every 10 frames)
                self._det_fps_count += 1
                if self._det_fps_count >= 10:
                    now = time.time()
                    elapsed = now - self._det_fps_ts
                    if elapsed > 0:
                        self._detection_fps = round(self._det_fps_count / elapsed, 1)
                    self._det_fps_ts = now
                    self._det_fps_count = 0
                if detection_count % 20 == 0:  # Log every 20 detections
                    print(f"[DetectionWorker] Processed {detection_count} frames, latest: {len(detections)} objects")

                # Outstretched hand gesture detection (YOLO Pose keypoints)
                # Run the hand check regardless of whether YOLO found anything.
                # A hand held close to the lens frequently is NOT classified as a
                # person, so gating on `detections` meant the check never ran in
                # exactly the situation it exists for.
                if _gesture_enabled:
                    _check_outstretched_hand(frame)

                if self._config_manager.is_alert_logging_enabled():
                    now = time.time()
                    if now - self._last_alert_log_ts >= self._alert_log_cooldown:
                        target_classes = self._config_manager.get_classes()
                        if not target_classes:
                            target_classes = list(
                                set(d['class_name'] if isinstance(d, dict) else d.class_name for d in detections)
                            )
                        logged = detection_logger.log_detections(frame, detections, target_classes)
                        if logged:
                            self._last_alert_log_ts = now
                            if detection_logger.detection_logs:
                                detection_logger.detection_logs[-1]['camera_source'] = camera_manager.camera_source

                # Emit telemetry for every detection frame (TelemetryManager handles its own throttling)
                telemetry = get_telemetry()
                if telemetry and telemetry.enabled and detections:
                    try:
                        telemetry.emit_detection(
                            detections=detections,
                            frame=frame,
                            robot_state=self._cached_robot_state,
                            vision_config=self._config_manager.get_vision_config(),
                            camera_source=camera_manager.camera_source,
                            frame_size=self._last_detection_frame_size,
                        )
                    except Exception as telem_err:
                        logger.debug(f"[Telemetry] Detection emit error: {telem_err}")

            except Exception as worker_error:
                print(f"[DetectionWorker] Error: {worker_error}")
            finally:
                self._detection_queue.task_done()

    def shutdown_detection_worker(self):
        """Stop the detection worker thread gracefully."""
        self._detection_stop_event.set()
        try:
            self._detection_queue.put_nowait(None)
        except queue.Full:
            pass
        if self._detection_thread:
            self._detection_thread.join(timeout=1.0)
            self._detection_thread = None

    def generate_frames(self):
        """Generate video frames for streaming with optimized performance"""
        import sys

        # Assign unique ID to this generator instance
        my_stream_id = self.stream_generation_id
        self.stream_generation_id += 1
        self.stream_active = True
        self._stream_exited.clear()

        print(f"Starting video stream generator (ID: {my_stream_id})")
        sys.stdout.flush()

        frame_count = 0

        if not self._config_manager:
            from config import get_config
            self._config_manager = get_config()
        self._ensure_detection_worker()

        # JPEG encoding parameters: quality 75 provides good balance of quality/size/speed
        # Lower quality = smaller files = faster transmission = less browser lag
        jpeg_params = [cv2.IMWRITE_JPEG_QUALITY, 75]

        # ------------------------------------------------------------------
        # Stream pacing. The yield path below had NO sleep, so this loop
        # re-encoded and re-sent the SAME frame as fast as the CPU allowed —
        # measured at 164 FPS / 97 Mbit/s. That saturates the link, floods the
        # browser decoder and starves thumbnail/API requests. The camera only
        # produces ~15 FPS, so anything above that is duplicate frames.
        # ------------------------------------------------------------------
        STREAM_TARGET_FPS = 15.0
        STREAM_MIN_INTERVAL = 1.0 / STREAM_TARGET_FPS
        last_emit_ts = 0.0

        while True:
            try:
                # Serve frames when YOLO-E is running OR PPE is running independently
                has_activity = self.is_running or _ppe_enabled
                if has_activity and camera_manager.is_camera_available():
                    frame = camera_manager.get_frame()
                    if frame is not None:
                        # Pace before spending CPU on draw + JPEG encode.
                        _dt = time.time() - last_emit_ts
                        if _dt < STREAM_MIN_INTERVAL:
                            time.sleep(STREAM_MIN_INTERVAL - _dt)
                        last_emit_ts = time.time()
                        frame_count += 1

                        if _ppe_enabled:
                            # PPE mode: draw compliance boxes only, never YOLO-E boxes
                            annotated_frame = frame
                            with _ppe_lock:
                                ppe_snap = _ppe_last_result
                            if ppe_snap and ppe_snap.get("people"):
                                annotated_frame = get_ppe_detector().draw_compliance(annotated_frame, ppe_snap)
                        elif self.is_running:
                            with self._detection_lock:
                                detections = list(self._last_detections or [])
                            annotated_frame = detector.draw_detections(frame, detections) if detections else frame
                        else:
                            annotated_frame = frame

                        # Optionally resize for web display (reduces bandwidth, improves browser performance)
                        # Scale to max width of 1280px if larger (maintains aspect ratio)
                        height, width = annotated_frame.shape[:2]
                        max_width = 1280
                        if width > max_width:
                            scale = max_width / width
                            new_width = max_width
                            new_height = int(height * scale)
                            annotated_frame = cv2.resize(annotated_frame, (new_width, new_height),
                                                        interpolation=cv2.INTER_AREA)

                        # Encode frame as JPEG with quality optimization (75% quality for speed)
                        ret, buffer = cv2.imencode('.jpg', annotated_frame, jpeg_params)
                        if ret:
                            frame_bytes = buffer.tobytes()
                            yield (b'--frame\r\n'
                                   b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                    else:
                        time.sleep(0.01)  # Reduced sleep when waiting for frames
                else:
                    # Detection stopped - exit gracefully instead of looping.
                    # Must consider PPE too: during a mode switch is_running goes
                    # False before _ppe_enabled goes True, and breaking in that
                    # window blanks the browser until it reconnects.
                    if not self.is_running and not _ppe_enabled:
                        print(f"🛑 Frame generation stopped - exiting stream (ID: {my_stream_id})")
                        break
                    time.sleep(0.1)
            except GeneratorExit:
                # Client disconnected - clean exit
                print(f"🔌 Client disconnected from video stream (ID: {my_stream_id})")
                break
            except Exception as e:
                print(f"❌ Error in frame generation: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(0.1)

        self.stream_active = False
        self._stream_exited.set()

web_app = WebApp()

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    """Video streaming route with optimized headers"""
    response = Response(web_app.generate_frames(),
                       mimetype='multipart/x-mixed-replace; boundary=frame')
    # Prevent caching to ensure fresh frames
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/start_detection', methods=['POST'])
def start_detection():
    """Start object detection with proper state synchronization"""
    print("🔍 WEB_APP: start_detection() endpoint called!")
    import sys; sys.stdout.flush()
    try:
        print(f"🚀 Starting detection - Current camera: {camera_manager.camera_source}")
        sys.stdout.flush()

        now = time.time()
        if now - web_app._last_start_request < web_app._throttle_window:
            wait_remaining = max(0.0, web_app._throttle_window - (now - web_app._last_start_request))
            print(f"⏳ Start request throttled - wait {wait_remaining:.1f}s before retrying")
            return jsonify({
                'status': 'error',
                'message': f'Start request ignored to prevent rapid restart. Retry in {wait_remaining:.1f}s.'
            }), 429
        web_app._last_start_request = now
        
        if web_app.is_running:
            web_app.is_running = False
            camera_manager.stop()
            web_app._stream_exited.wait(timeout=3.0)

        # Start camera
        camera_started = camera_manager.start()

        if camera_started:
            web_app.is_running = True
            web_app._ensure_detection_worker()
            web_app._start_detection_feeder()
            print(f"✅ Detection started successfully with {camera_manager.camera_source}")
            return jsonify({'status': 'success', 'message': 'Detection started'})
        else:
            web_app.is_running = False
            print(f"❌ Failed to start camera: {camera_manager.camera_source}")
            return jsonify({'status': 'error', 'message': f'Failed to start {camera_manager.camera_source} camera'})
    except Exception as e:
        web_app.is_running = False
        print(f"❌ Detection start error: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/stop_detection', methods=['POST'])
def stop_detection():
    """Stop object detection with complete cleanup"""
    try:
        print(f"🛑 Stopping detection - Current camera: {camera_manager.camera_source}")

        now = time.time()
        if now - web_app._last_stop_request < web_app._throttle_window:
            wait_remaining = max(0.0, web_app._throttle_window - (now - web_app._last_stop_request))
            print(f"⏳ Stop request throttled - wait {wait_remaining:.1f}s before retrying")
            return jsonify({
                'status': 'error',
                'message': f'Stop request ignored to prevent rapid restart. Retry in {wait_remaining:.1f}s.'
            }), 429
        web_app._last_stop_request = now

        # Set state first to stop loops
        global _ppe_enabled, _ppe_last_result
        web_app.is_running = False
        # Stop PPE as well. Stop must mean "stop everything" - otherwise pressing
        # Stop while in PPE mode leaves the PPE worker running and the stream
        # alive, so the button appears to do nothing.
        _ppe_enabled = False
        with _ppe_lock:
            _ppe_last_result = None
        web_app._stop_detection_feeder()
        web_app.shutdown_detection_worker()

        camera_manager.stop()
        web_app._stream_exited.wait(timeout=3.0)
        return jsonify({'status': 'success', 'message': 'Detection stopped'})

    except Exception as e:
        print(f"❌ Stop detection error: {e}")
        web_app.is_running = False  # Ensure state is clean even on error
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/switch_camera', methods=['POST'])
def switch_camera():
    """Switch camera source with safe state management"""
    data = request.json
    camera_source = data.get('source', 'mac')
    robot_ip = data.get('robot_ip', '192.168.87.25')
    rtsp_url = data.get('rtsp_url', None)
    
    print(f"🔄 Switch camera request: source={camera_source}, ip={robot_ip}, rtsp_url={rtsp_url}")
    
    try:
        # Remember if detection was running
        was_running = web_app.is_running
        
        # Always stop detection first for clean switching
        if was_running:
            print("🛑 Stopping detection for camera switch")
            web_app.is_running = False
            camera_manager.stop()
            
            # Give time for cleanup
            import time
            time.sleep(0.2)
        
        # Switch camera source
        print(f"🔄 Switching from {camera_manager.camera_source} to {camera_source}")
        camera_manager.set_camera_source(camera_source, robot_ip, rtsp_url)
        
        # If detection was running, restart it with new source
        if was_running:
            print(f"🚀 Restarting detection with new camera: {camera_source}")
            if camera_manager.start():
                web_app.is_running = True
                print(f"✅ Camera switched and detection restarted: {camera_source}")
                return jsonify({
                    'status': 'success', 
                    'message': f'Switched to {camera_source} camera and restarted detection'
                })
            else:
                print(f"⚠️ Camera switched but failed to restart detection: {camera_source}")
                return jsonify({
                    'status': 'warning', 
                    'message': f'Switched to {camera_source} but detection failed to start'
                })
        else:
            print(f"✅ Camera source switched to {camera_source}")
            return jsonify({'status': 'success', 'message': f'Switched to {camera_source} camera'})
            
    except Exception as e:
        print(f"❌ Error switching camera: {e}")
        # Ensure clean state on error
        web_app.is_running = False
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
        'is_running': web_app.is_running and camera_manager.is_running,
        'camera_available': camera_manager.is_camera_available(),
        'camera_status': camera_status,
        'current_model': detector.get_current_model()
    })

@app.route('/go2/battery')
def go2_battery():
    """Proxy endpoint for GO2 battery data to avoid CORS issues"""
    try:
        response = requests.get(f'{robot_host.service_url()}/battery', timeout=2)
        if response.status_code == 200:
            return jsonify(response.json())
        else:
            return jsonify({'connected': False, 'soc': None}), response.status_code
    except Exception as e:
        robot_host.report_failure()
        logger.error(f"Failed to fetch GO2 battery: {e}")
        return jsonify({'connected': False, 'soc': None, 'error': str(e)}), 503

@app.route('/go2/video_passthrough')
def go2_video_passthrough():
    """Zero-copy proxy that relays the GO2 MJPEG stream for low-latency viewing."""
    def proxy():
        try:
            with requests.get(f'{robot_host.service_url()}/video_feed', stream=True, timeout=(3, 30)) as resp:
                resp.raise_for_status()
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
        except Exception as err:
            logger.error(f"GO2 passthrough error: {err}")
    response = Response(proxy(), mimetype='multipart/x-mixed-replace; boundary=frame')
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/detections/latest')
def latest_detections():
    """Expose the freshest detection metadata for the UI overlay."""
    with web_app._detection_lock:
        detections = list(web_app._last_detections or [])
        ts = web_app._last_detection_ts
        frame_size = web_app._last_detection_frame_size
    detections_payload = []
    for detection in detections:
        detections_payload.append({
            'bbox': detection.bbox,
            'class_id': detection.class_id,
            'class_name': detection.class_name,
            'confidence': detection.confidence
        })
    width, height = frame_size
    return jsonify({
        'timestamp': ts,
        'detections': detections_payload,
        'frame_width': width,
        'frame_height': height,
        'camera_source': camera_manager.camera_source
    })

# ── Gesture detection (YOLO Pose outstretched hand) ─────────────────
# A person walking past at 10+ feet will have a tiny bbox (fails #2).
# A person standing close will be tall & narrow (fails #1).
# A person's head/torso cropped at frame edge may have odd aspect but
# won't be large enough or low enough (fails #2 or #3).
_GESTURE_COOLDOWN = 5.0    # seconds between shake triggers
_gesture_last_trigger_ts = 0.0
_gesture_count = 0
_gesture_enabled = False    # toggled by scene narrator mode

# ---------------------------------------------------------------------------
# PPE compliance detection. Runs in its own worker thread so it never shares a
# code path with YOLO-E; exactly one of the two is active at a time, selected
# via /api/detection/mode. Ported from the Plano PoC 2026-09-02.
# ---------------------------------------------------------------------------
_ppe_enabled = False
_ppe_last_result = None
_ppe_lock = threading.Lock()
_mode_switch_lock = threading.Lock()  # serialize /api/detection/mode
_ppe_thread = None


def _ppe_worker_loop():
    """Independent PPE loop — pulls frames straight from camera_manager."""
    global _ppe_last_result
    pd = get_ppe_detector()
    logger.info("[PPE] Worker thread started on %s", pd.device)
    while _ppe_enabled:
        if not camera_manager.is_camera_available():
            time.sleep(0.5); continue
        frame = camera_manager.get_frame()
        if frame is None:
            time.sleep(0.1); continue
        if not pd.should_run_this_frame():
            time.sleep(0.02); continue
        try:
            result = pd.detect(frame)
        except Exception as e:
            logger.warning("[PPE] detect failed: %s", e)
            time.sleep(0.25); continue
        result['_ts'] = time.time()
        with _ppe_lock:
            _ppe_last_result = result

        # Log non-compliance to the detection log so violations show up in the
        # right-hand pane. The thumbnail is taken from the ANNOTATED frame so the
        # red/green boxes are visible in the log tile, not just the live stream.
        people = result.get('people') or []
        violations = [pp for pp in people if not pp.get('compliant')]
        if violations:
            try:
                from types import SimpleNamespace
                dets = [SimpleNamespace(class_name='PPE Violation',
                                        confidence=float(pp.get('confidence') or 0.0))
                        for pp in violations]
                annotated = pd.draw_compliance(frame, result)
                if detection_logger.log_detections(annotated, dets, ['PPE Violation']):
                    if detection_logger.detection_logs:
                        detection_logger.detection_logs[-1]['camera_source'] = camera_manager.camera_source
                    logger.info("[PPE] %d violation(s), %d compliant (%.0fms)",
                                len(violations), len(people) - len(violations),
                                result.get('inference_ms', 0))
            except Exception as e:
                logger.warning("[PPE] violation logging failed: %s", e)
        time.sleep(0.02)
    logger.info("[PPE] Worker thread stopped")


def _check_outstretched_hand(frame):
    """Run YOLO Pose keypoint detection for outstretched hand and fire shake.

    Uses the lightweight yolo11n-pose model (~6MB) to check shoulder-elbow-wrist
    geometry.  Runs on the raw detection frame — no extra capture needed.
    """
    global _gesture_last_trigger_ts, _gesture_count
    if not _gesture_enabled:
        return
    now = time.time()
    if (now - _gesture_last_trigger_ts) < _GESTURE_COOLDOWN:
        return

    gd = get_gesture_detector()
    if not gd.should_run_this_frame():
        return

    # An open hand held near the camera is the trigger. Pose keypoints cannot
    # express this (COCO-17 has a wrist and no fingers), so use the hand
    # detector and gate on how much of the frame the hand occupies.
    hd = get_hand_detector()
    hres = hd.detect(frame)
    result = {"detected": hres["detected"],
              "confidence": hres["confidence"],
              "arm": "hand",
              "person_count": 0,
              "inference_ms": hres["inference_ms"],
              "area_frac": hres["area_frac"],
              "fingers": hres["fingers"]}

    if result["detected"]:
        _gesture_last_trigger_ts = now
        _gesture_count += 1
        logger.info(
            f"[Gesture] Open hand near camera! area={result['area_frac']*100:.1f}% "
            f"conf={result['confidence']:.2f} fingers={result['fingers']} "
            f"ms={result['inference_ms']:.0f} — firing shake #{_gesture_count}"
        )
        _gesture_shake_callback(f"outstretched_hand_{result['arm']}")


_go2_last_move_ts = 0.0
_go2_last_command_ts = 0.0
_go2_watchdog_thread = None
_go2_watchdog_running = False
_GO2_MOVE_TIMEOUT = 0.6
# True while a /move request is awaiting the robot. The first Move includes a
# BalanceStand and can take ~3s; the watchdog must not fire /stop during it.
_go2_move_inflight = False
_go2_move_inflight_lock = threading.Lock()
_GO2_COMMAND_COOLDOWN = 1.5
_GO2_MAX_VX = 0.25
_GO2_MAX_VY = 0.2
_GO2_MAX_VYAW = 0.5
# Robot address is resolved at call time by robot_host (see robot_host.py).


def _go2_watchdog_loop():
    global _go2_watchdog_running
    _go2_watchdog_running = True
    while _go2_watchdog_running:
        with _go2_move_inflight_lock:
            _inflight = _go2_move_inflight
        if (not _inflight) and _go2_last_move_ts > 0 and (time.time() - _go2_last_move_ts) > _GO2_MOVE_TIMEOUT:
            try:
                requests.post(f'{robot_host.service_url()}/stop', json={}, timeout=1)
                logger.debug("[GO2 Watchdog] Auto-stop — no move command received")
            except Exception:
                pass
        time.sleep(0.2)


def _ensure_go2_watchdog():
    global _go2_watchdog_thread
    if _go2_watchdog_thread and _go2_watchdog_thread.is_alive():
        return
    _go2_watchdog_thread = threading.Thread(target=_go2_watchdog_loop, daemon=True, name="go2-watchdog")
    _go2_watchdog_thread.start()
    logger.info("[GO2 Watchdog] Started — auto-stop after %.1fs idle", _GO2_MOVE_TIMEOUT)


@app.route('/go2/command', methods=['POST'])
def go2_command():
    global _go2_last_command_ts, _go2_last_move_ts
    try:
        data = request.get_json()
        command = data.get('command')

        if not command:
            return jsonify({'success': False, 'message': 'No command specified'}), 400

        now = time.time()
        if (now - _go2_last_command_ts) < _GO2_COMMAND_COOLDOWN:
            remaining = _GO2_COMMAND_COOLDOWN - (now - _go2_last_command_ts)
            return jsonify({'success': False, 'message': f'Cooldown — wait {remaining:.1f}s'}), 429

        logger.info(f"Sending GO2 command: {command}")
        _go2_last_command_ts = now

        # Kill the move watchdog when issuing posture commands — the watchdog
        # sends /stop repeatedly which triggers BalanceStand on a standing robot
        _go2_last_move_ts = 0.0

        response = requests.post(f'{robot_host.service_url()}/command',
                                json={'command': command},
                                timeout=5)

        if response.status_code == 200:
            result = response.json()
            logger.info(f"GO2 command '{command}' result: {result}")
            telemetry = get_telemetry()
            if telemetry and telemetry.enabled:
                try:
                    telemetry.emit_command(
                        command=command,
                        success=result.get('success', False),
                        message=result.get('message', ''),
                        robot_state=web_app._cached_robot_state,
                    )
                except Exception:
                    pass
            return jsonify(result)
        else:
            logger.error(f"GO2 command '{command}' failed with status {response.status_code}")
            return jsonify({'success': False, 'message': f'Command failed with status {response.status_code}'}), response.status_code

    except Exception as e:
        logger.error(f"Failed to send GO2 command: {e}")
        return jsonify({'success': False, 'message': str(e)}), 503

@app.route('/go2/move', methods=['POST'])
def go2_move():
    global _go2_last_move_ts
    _ensure_go2_watchdog()
    try:
        data = request.get_json()
        vx = max(-_GO2_MAX_VX, min(_GO2_MAX_VX, float(data.get('vx', 0))))
        vy = max(-_GO2_MAX_VY, min(_GO2_MAX_VY, float(data.get('vy', 0))))
        vyaw = max(-_GO2_MAX_VYAW, min(_GO2_MAX_VYAW, float(data.get('vyaw', 0))))

        _go2_last_move_ts = time.time()
        global _go2_move_inflight
        with _go2_move_inflight_lock:
            _go2_move_inflight = True
        try:
            # Must exceed the Orin's own 3.0s move-result timeout, or this proxy
            # gives up before the robot can answer.
            response = requests.post(f'{robot_host.service_url()}/move',
                json={'vx': vx, 'vy': vy, 'vyaw': vyaw},
                timeout=4
            )
        finally:
            with _go2_move_inflight_lock:
                _go2_move_inflight = False
            _go2_last_move_ts = time.time()
        return jsonify(response.json()), response.status_code
    except Exception as e:
        _go2_last_move_ts = 0.0
        robot_host.report_failure()   # a venue change looks like a connection error
        return jsonify({'success': False, 'message': str(e)}), 503

@app.route('/go2/stop', methods=['POST'])
def go2_stop():
    global _go2_last_move_ts
    _go2_last_move_ts = 0.0
    try:
        response = requests.post(f'{robot_host.service_url()}/stop',
            json={},
            timeout=3
        )
        return jsonify(response.json()), response.status_code
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 503

@app.route('/go2/motion_mode', methods=['POST'])
def go2_motion_mode():
    """Proxy endpoint to adjust the GO2 motion mode (e.g., set to normal)."""
    try:
        data = request.get_json() or {}
        mode = data.get('mode', 'normal')

        logger.info(f"Setting GO2 motion mode to: {mode}")

        response = requests.post(f'{robot_host.service_url()}/motion_mode',
                                 json={'mode': mode},
                                 timeout=5)

        if response.status_code == 200:
            result = response.json()
            logger.info(f"GO2 motion mode '{mode}' result: {result}")
            return jsonify(result)
        else:
            logger.error(f"GO2 motion mode '{mode}' failed with status {response.status_code}")
            return jsonify({'success': False, 'message': f'Mode switch failed with status {response.status_code}'}), response.status_code

    except Exception as e:
        logger.error(f"Failed to set GO2 motion mode: {e}")
        return jsonify({'success': False, 'message': str(e)}), 503

@app.route('/switch_model', methods=['POST'])
def switch_detection_model():
    """Switch between different YOLO models"""
    data = request.json
    model_type = data.get('model_type', 'yoloe')
    
    print(f"Switch model request: {model_type}")
    
    try:
        success = detector.switch_model(model_type)
        if success:
            return jsonify({
                'status': 'success', 
                'message': f'Switched to {model_type} model',
                'current_model': detector.get_current_model()
            })
        else:
            return jsonify({
                'status': 'error', 
                'message': f'Failed to switch to {model_type} model',
                'current_model': detector.get_current_model()
            })
    except Exception as e:
        print(f"Error switching model: {e}")
        return jsonify({
            'status': 'error', 
            'message': str(e),
            'current_model': detector.get_current_model()
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

@app.route('/api/telemetry/stats')
def telemetry_stats():
    """Return telemetry exporter statistics."""
    telemetry = get_telemetry()
    if not telemetry:
        return jsonify({'enabled': False})
    return jsonify(telemetry.get_stats())

@app.route('/api/scene')
def scene_narration():
    narrator = get_narrator()
    if not narrator or not narrator.enabled:
        return jsonify({'enabled': False, 'entries': []})
    since = request.args.get('since')
    entries = narrator.get_log(since=since)
    return jsonify({'enabled': True, 'entries': entries})

@app.route('/api/scene/context', methods=['GET'])
def get_scene_context():
    narrator = get_narrator()
    if not narrator:
        return jsonify({'scene_context': ''})
    return jsonify({'scene_context': narrator.scene_context or ''})

@app.route('/api/scene/context', methods=['POST'])
def set_scene_context():
    narrator = get_narrator()
    if not narrator:
        return jsonify({'success': False, 'message': 'Narrator not initialized'}), 503
    data = request.get_json()
    narrator.scene_context = data.get('scene_context', '').strip() or None
    return jsonify({'success': True})

@app.route('/api/scene/mode', methods=['GET'])
def get_scene_mode():
    """Return the current narrator mode + gesture detection stats."""
    narrator = get_narrator()
    if not narrator:
        return jsonify({'enabled': False})
    status = narrator.get_status()
    # Overlay YOLO Pose gesture stats
    now = time.time()
    remaining = max(0, _GESTURE_COOLDOWN - (now - _gesture_last_trigger_ts))
    status['gesture_count'] = _gesture_count
    status['gesture_cooldown_remaining'] = round(remaining, 1)
    status['gesture_cooldown_seconds'] = _GESTURE_COOLDOWN
    status['gesture_method'] = 'yolo_pose'
    return jsonify(status)

@app.route('/api/scene/mode', methods=['POST'])
def set_scene_mode():
    """Toggle between 'casual' and 'gesture' modes."""
    narrator = get_narrator()
    if not narrator:
        return jsonify({'success': False, 'message': 'Narrator not initialized'}), 503
    data = request.get_json()
    mode = data.get('mode', '').strip().lower()
    if mode not in ('casual', 'gesture'):
        return jsonify({'success': False, 'message': f'Invalid mode: {mode}'}), 400
    global _gesture_enabled
    narrator.set_mode(mode)
    # The slider is the gesture on/off control: 'gesture' arms, any other mode
    # disarms. Firing a shake is a physical action, so the transition is always
    # logged (never silent) and the operator can still override via
    # POST /api/gesture {"enabled": ...}.
    want = (mode == 'gesture')
    if want != _gesture_enabled:
        _gesture_enabled = want
        logger.info("[GesturePose] %s via narrator slider (mode=%s)",
                    'ARMED' if want else 'DISARMED', mode)
    return jsonify({'success': True, 'mode': narrator.mode})

@app.route('/api/scene/summary')
def get_scene_summary():
    """Return the aggregated scene awareness summary."""
    narrator = get_narrator()
    if not narrator or not narrator.enabled:
        return jsonify({'enabled': False, 'summary': None})
    data = narrator.get_scene_summary()
    data['enabled'] = True
    return jsonify(data)

@app.route('/api/scene/summary/clear', methods=['POST'])
def clear_scene_summary():
    """Clear scene summary and observation history (fresh shift)."""
    narrator = get_narrator()
    if not narrator:
        return jsonify({'success': False, 'message': 'Narrator not initialized'}), 503
    narrator.clear_scene()
    return jsonify({'success': True})

@app.route('/api/scene/frame/clear', methods=['POST'])
def clear_frame_log():
    """Clear frame observation log."""
    narrator = get_narrator()
    if not narrator:
        return jsonify({'success': False, 'message': 'Narrator not initialized'}), 503
    narrator.clear_frame_log()
    return jsonify({'success': True})

@app.route('/api/vlm/pause', methods=['POST'])
def toggle_vlm_pause():
    """Pause or resume VLM processing (frame observations + scene summary)."""
    narrator = get_narrator()
    if not narrator:
        return jsonify({'success': False, 'message': 'Narrator not initialized'}), 503
    data = request.get_json() or {}
    should_pause = data.get('paused', not narrator.paused)  # toggle if not specified
    if should_pause:
        narrator.pause()
    else:
        narrator.resume()
    return jsonify({'success': True, 'paused': narrator.paused})

@app.route('/api/detections/pause', methods=['POST'])
def toggle_detection_pause():
    """Pause or resume YOLO detection processing."""
    data = request.get_json() or {}
    should_pause = data.get('paused', not web_app._detection_paused)  # toggle
    web_app._detection_paused = should_pause
    logger.info(f"[Detections] {'PAUSED' if should_pause else 'RESUMED'}")
    return jsonify({'success': True, 'paused': web_app._detection_paused})

@app.route('/api/pause/status')
def pause_status():
    """Return pause state for both VLM and detections."""
    narrator = get_narrator()
    vlm_paused = narrator.paused if narrator else False
    return jsonify({
        'vlm_paused': vlm_paused,
        'detection_paused': web_app._detection_paused,
    })

@app.route('/thumbnail/<filename>')
def serve_thumbnail(filename):
    """Serve thumbnail images"""
    try:
        thumbnail_path = os.path.join(detection_logger.log_dir, "thumbnails", filename)
        # A zero-byte file satisfies exists() but renders as a broken image.
        # Treat it as missing so the UI can fall back cleanly.
        if os.path.exists(thumbnail_path) and os.path.getsize(thumbnail_path) > 0:
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
        if os.path.exists(image_path) and os.path.getsize(image_path) > 0:
            return send_file(image_path, mimetype='image/jpeg')
        
        # Fallback to thumbnail for older entries (will be upscaled by CSS)
        thumbnail_path = os.path.join(detection_logger.log_dir, "thumbnails", filename)
        if os.path.exists(thumbnail_path):
            return send_file(thumbnail_path, mimetype='image/jpeg')
        
        return jsonify({'error': 'Image not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/yoloe/config', methods=['GET'])
def get_yoloe_config():
    """Get current YOLO-E configuration"""
    try:
        from config import get_config
        config_manager = get_config()
        vision_config = config_manager.get_vision_config()

        # Get visual prompts with class names for UI display
        visual_prompts_with_names = config_manager.get_visual_prompts_with_names()

        return jsonify({
            'status': 'success',
            'detector': vision_config.get('detector', 'yoloe'),
            'detection_mode': config_manager.get_detection_mode(),
            'conf': vision_config.get('conf', 0.25),
            'iou': vision_config.get('iou', 0.45),
            'max_det': vision_config.get('max_det', 100),
            'classes': config_manager.get_classes(),
            'visual_prompts': visual_prompts_with_names,  # Return structured format with class names
            'model_path': config_manager.get_model_path(),
            'source': vision_config.get('source', ''),
            'rtsp_tcp': vision_config.get('rtsp_tcp', True),
            'alert_logging': config_manager.is_alert_logging_enabled(),
            'nlp_enabled': config_manager.is_nlp_enabled(),
            'nlp_prompt': config_manager.get_nlp_prompt(),
            'openai_api_key': config_manager.get_openai_api_key()
        })
    except Exception as e:
        print(f"❌ Error getting YOLO-E config: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/yoloe/config', methods=['POST'])
def save_yoloe_config():
    """Save YOLO-E configuration"""
    try:
        from config import get_config
        config_manager = get_config()
        data = request.json
        
        # Update vision configuration
        vision_config = config_manager.config['vision']
        vision_config.update({
            'detector': data.get('detector', 'yoloe'),
            'conf': float(data.get('conf', 0.25)),
            'iou': float(data.get('iou', 0.45)),
            'max_det': int(data.get('max_det', 100))
        })
        
        # Update classes (text prompts)
        classes = data.get('classes', [])
        if isinstance(classes, str):
            classes = [c.strip() for c in classes.split(',') if c.strip()]
        config_manager.update_classes(classes)
        
        # Update alert logging setting
        if 'alert_logging' in data:
            config_manager.set_alert_logging(bool(data['alert_logging']))

        # Update detection mode if explicitly set
        detection_mode = data.get('detection_mode', '')
        if detection_mode:
            config_manager.set_detection_mode(detection_mode)
            print(f"✅ Detection mode set to: {detection_mode}")

        # Update NLP prompt if provided
        nlp_prompt = data.get('nlp_prompt', '').strip()
        if nlp_prompt:
            config_manager.set_nlp_prompt(nlp_prompt, enabled=False)  # Don't override detection_mode
            print(f"✅ NLP prompt updated: '{nlp_prompt}'")

        # Backward compatibility: handle old nlp_enabled flag
        if 'nlp_enabled' in data:
            nlp_enabled = data.get('nlp_enabled', False)
            if nlp_enabled:
                config_manager.set_detection_mode('nlp')
                print("✅ Detection mode set to NLP (via nlp_enabled flag)")
            else:
                # Don't automatically disable - user should set mode explicitly
                pass

        # Update OpenAI API key if provided
        if 'openai_api_key' in data:
            api_key = data.get('openai_api_key', '').strip()
            if api_key:
                config_manager.set_openai_api_key(api_key)
                print("✅ OpenAI API key updated")

        # Save configuration to file
        config_manager.save_config()
        
        # Reload detector configuration if using YOLO-E
        if vision_config['detector'] == 'yoloe':
            try:
                from yoloe_detector import get_yoloe_detector
                yoloe_detector = get_yoloe_detector()
                yoloe_detector.reload_config()
                print("✅ YOLO-E detector configuration reloaded")
            except Exception as reload_error:
                print(f"⚠️ Failed to reload YOLO-E detector: {reload_error}")
        
        return jsonify({
            'status': 'success',
            'message': 'Configuration saved successfully'
        })
        
    except Exception as e:
        print(f"❌ Error saving YOLO-E config: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/yoloe/test_nlp', methods=['POST'])
def test_nlp_mapping():
    """Test NLP prompt mapping to YOLO classes"""
    try:
        data = request.json
        api_key = data.get('api_key', '').strip()
        nlp_prompt = data.get('nlp_prompt', '').strip()

        if not api_key:
            return jsonify({'status': 'error', 'error': 'API key is required'}), 400

        if not nlp_prompt:
            return jsonify({'status': 'error', 'error': 'NLP prompt is required'}), 400

        # Import and use NLP mapper
        from nlp_mapper import get_nlp_mapper
        mapper = get_nlp_mapper(api_key)

        # Get mapping with explanations
        result = mapper.map_prompt_with_explanations(nlp_prompt)

        return jsonify({
            'status': 'success',
            'classes': result.get('classes', []),
            'explanation': result.get('explanation', ''),
            'confidence': result.get('confidence', 0.0)
        })

    except Exception as e:
        print(f"❌ Error testing NLP mapping: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'status': 'error', 'error': str(e)}), 500

@app.route('/api/yoloe/visual_prompts', methods=['POST'])
def upload_visual_prompts():
    """Upload visual prompt images with class names"""
    try:
        from config import get_config
        import os
        import shutil
        config_manager = get_config()
        
        if 'images' not in request.files:
            return jsonify({'status': 'error', 'message': 'No images provided'}), 400
        
        files = request.files.getlist('images')
        if not files or files[0].filename == '':
            return jsonify({'status': 'error', 'message': 'No valid images provided'}), 400
        
        # Get class names from form data
        class_names = request.form.getlist('class_names')
        
        # Create visual_prompts directory if it doesn't exist
        prompts_dir = 'visual_prompts'
        os.makedirs(prompts_dir, exist_ok=True)
        
        uploaded_prompts = []
        valid_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp'}
        
        for i, file in enumerate(files):
            if file and file.filename:
                filename = file.filename.lower()
                file_ext = os.path.splitext(filename)[1]
                
                if file_ext in valid_extensions:
                    # Generate safe filename
                    import time
                    import uuid
                    safe_filename = f"prompt_{int(time.time())}_{str(uuid.uuid4())[:8]}{file_ext}"
                    file_path = os.path.join(prompts_dir, safe_filename)
                    
                    # Save file
                    file.save(file_path)
                    
                    # Get class name for this file (if provided)
                    class_name = class_names[i] if i < len(class_names) and class_names[i] else None
                    
                    # Add to configuration with class name
                    if config_manager.add_visual_prompt(file_path, class_name):
                        uploaded_prompts.append({
                            'filename': safe_filename,
                            'class_name': class_name or f'custom-{i+1}',
                            'path': file_path
                        })
                        print(f"✅ Visual prompt saved: {file_path} (class: {class_name or f'custom-{i+1}'})")
                    else:
                        os.remove(file_path)  # Clean up if config add failed
                else:
                    print(f"⚠️ Skipped invalid file type: {filename}")
        
        if uploaded_prompts:
            # Save updated configuration
            config_manager.save_config()
            
            # Reload detector if using YOLO-E
            try:
                from yoloe_detector import get_yoloe_detector
                yoloe_detector = get_yoloe_detector()
                yoloe_detector.reload_config()
                print("✅ YOLO-E detector visual prompts reloaded")
            except Exception as reload_error:
                print(f"⚠️ Failed to reload YOLO-E detector: {reload_error}")
            
            return jsonify({
                'status': 'success',
                'message': f'Uploaded {len(uploaded_prompts)} visual prompt(s)',
                'uploaded': len(uploaded_prompts),
                'prompts': uploaded_prompts
            })
        else:
            return jsonify({'status': 'error', 'message': 'No valid images were uploaded'}), 400
            
    except Exception as e:
        print(f"❌ Error uploading visual prompts: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/yoloe/visual_prompts', methods=['GET'])
def get_visual_prompts():
    """Get current visual prompts with class names"""
    try:
        from config import get_config
        config_manager = get_config()
        
        prompts_with_names = config_manager.get_visual_prompts_with_names()
        
        return jsonify({
            'status': 'success',
            'visual_prompts': prompts_with_names
        })
        
    except Exception as e:
        print(f"❌ Error getting visual prompts: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/yoloe/visual_prompts/<filename>', methods=['DELETE'])
def remove_visual_prompt(filename):
    """Remove a visual prompt image"""
    try:
        from config import get_config
        import os
        config_manager = get_config()
        
        # Find the full path
        prompts_dir = 'visual_prompts'
        file_path = os.path.join(prompts_dir, filename)
        
        # Remove from configuration
        if config_manager.remove_visual_prompt(file_path):
            # Delete the actual file
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"✅ Visual prompt removed: {file_path}")
            
            # Save updated configuration
            config_manager.save_config()
            
            # Reload detector if using YOLO-E
            try:
                from yoloe_detector import get_yoloe_detector
                yoloe_detector = get_yoloe_detector()
                yoloe_detector.reload_config()
                print("✅ YOLO-E detector visual prompts reloaded")
            except Exception as reload_error:
                print(f"⚠️ Failed to reload YOLO-E detector: {reload_error}")
            
            return jsonify({
                'status': 'success',
                'message': 'Visual prompt removed successfully'
            })
        else:
            return jsonify({'status': 'error', 'message': 'Visual prompt not found in configuration'}), 404
            
    except Exception as e:
        print(f"❌ Error removing visual prompt: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/visual_prompts/<filename>')
def serve_visual_prompt(filename):
    """Serve visual prompt images"""
    try:
        prompts_dir = 'visual_prompts'
        file_path = os.path.join(prompts_dir, filename)
        if os.path.exists(file_path):
            return send_file(file_path)
        else:
            return jsonify({'error': 'Visual prompt not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

_ssh_client = None
_ssh_lock = threading.Lock()

def ssh_exec_command(command):
    """Execute SSH command on Orin using a persistent paramiko connection."""
    global _ssh_client
    import paramiko
    with _ssh_lock:
        try:
            if _ssh_client is None or _ssh_client.get_transport() is None or not _ssh_client.get_transport().is_active():
                _ssh_client = paramiko.SSHClient()
                _ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                _ssh_client.connect(
                    os.environ.get('ORIN_HOST') or robot_host.host(),
                    username=os.environ.get('ORIN_USER', 'unitree'),
                    # No default: this repository is public. Set ORIN_PASS in the
                    # systemd unit or the environment. RTSP control is disabled by
                    # default anyway (the server costs ~103% CPU at idle).
                    password=os.environ.get('ORIN_PASS', ''),
                    timeout=5,
                )
            stdin, stdout, stderr = _ssh_client.exec_command(command, timeout=10)
            exit_code = stdout.channel.recv_exit_status()
            output = stdout.read().decode('utf-8').strip()
            error = stderr.read().decode('utf-8').strip()
            return exit_code, output, error
        except Exception as e:
            _ssh_client = None
            raise Exception(f"SSH command failed: {str(e)}")

@app.route('/rtsp/status', methods=['GET'])
def rtsp_status():
    """Check if RTSP server is running on the Orin"""
    try:
        exit_code, output, error = ssh_exec_command('sudo systemctl is-active rtsp-camera.service')
        is_running = exit_code == 0 and 'active' in output
        return jsonify({
            'status': 'success',
            'running': is_running,
            'message': 'RTSP server is running' if is_running else 'RTSP server is stopped'
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/rtsp/start', methods=['POST'])
def rtsp_start():
    """Start RTSP server on the Orin"""
    try:
        ssh_exec_command('sudo systemctl start rtsp-camera.service')
        for _ in range(6):
            time.sleep(0.5)
            exit_code, output, error = ssh_exec_command('sudo systemctl is-active rtsp-camera.service')
            if exit_code == 0 and 'active' in output:
                break

        if exit_code == 0 and 'active' in output:
            return jsonify({
                'status': 'success',
                'message': 'RTSP server started successfully'
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'RTSP server failed to start'
            }), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/rtsp/stop', methods=['POST'])
def rtsp_stop():
    """Stop RTSP server on the Orin"""
    try:
        # Stop RTSP systemd service
        ssh_exec_command('sudo systemctl stop rtsp-camera.service')
        for _ in range(4):
            time.sleep(0.5)
            exit_code, output, error = ssh_exec_command('sudo systemctl is-active rtsp-camera.service')
            if 'inactive' in output or exit_code != 0:
                break

        # systemctl is-active returns exit code 3 when inactive
        if 'inactive' in output or exit_code != 0:
            return jsonify({
                'status': 'success',
                'message': 'RTSP server stopped successfully'
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'RTSP server failed to stop'
            }), 500
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

def _refresh_robot_state():
    """Fetch battery/status from go2_service and cache for telemetry."""
    try:
        resp = requests.get(f'{robot_host.service_url()}/battery', timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            web_app._cached_robot_state.update({
                'soc': data.get('soc'),
                'voltage': data.get('voltage'),
                'current': data.get('current'),
                'connected': data.get('connected', False),
            })
    except Exception:
        pass


def _build_heartbeat_event():
    """Collect system state for periodic heartbeat telemetry."""
    import psutil
    _refresh_robot_state()
    from config import get_config
    cfg = get_config()
    telemetry = get_telemetry()
    if not telemetry or not telemetry.enabled:
        return None
    # Check if go2_service is reachable
    go2_reachable = False
    try:
        r = requests.get(f'{robot_host.service_url()}/status', timeout=2)
        go2_reachable = r.status_code == 200
    except Exception:
        pass

    telemetry.emit_heartbeat(
        robot_state=web_app._cached_robot_state,
        system_health={
            'stream_active': web_app.stream_active,
            'detection_worker_alive': (
                web_app._detection_thread is not None
                and web_app._detection_thread.is_alive()
            ),
            'detection_fps': web_app._detection_fps,
            'frames_processed': web_app._frames_processed,
            'go2_service_reachable': go2_reachable,
            'rtsp_server_running': None,  # unknown from AGX side
        },
        vision_config=cfg.get_vision_config(),
    )


def _init_telemetry():
    """Initialize and start the telemetry subsystem if enabled."""
    from config import get_config
    cfg = get_config()
    telemetry_cfg = cfg.get_telemetry_config()
    if not telemetry_cfg.get('enabled', False):
        logger.info("[Telemetry] Disabled in config — skipping init")
        return
    tm = init_telemetry(cfg.config)
    tm.start()
    tm.start_heartbeat(_build_heartbeat_event)
    atexit.register(tm.stop)
    logger.info("[Telemetry] Initialized and running")


_init_telemetry()


def _gesture_shake_callback(gesture_text: str):
    """Called when an outstretched-hand gesture is detected.

    Sends the GO2 'shake' command in a fire-and-forget thread so the
    detection loop is not blocked. The go2_service busy-guard will reject
    the command if the robot is already executing something.
    """
    def _send():
        try:
            logger.info(f"[Gesture] Sending GO2 shake — triggered by: '{gesture_text}'")
            resp = requests.post(
                f'{robot_host.service_url()}/command',
                json={'command': 'shake'},
                timeout=8,
            )
            if resp.status_code == 200:
                result = resp.json()
                logger.info(f"[Gesture] GO2 shake result: {result}")
            elif resp.status_code == 429:
                logger.info(f"[Gesture] GO2 shake rejected (robot busy/cooldown) — safe to ignore")
            else:
                logger.warning(f"[Gesture] GO2 shake failed: {resp.status_code}")
        except Exception as e:
            logger.error(f"[Gesture] GO2 shake request error: {e}")
    threading.Thread(target=_send, daemon=True, name="gesture-shake").start()


def _init_scene_narrator():
    """Initialize scene narrator if enabled in config."""
    from config import get_config
    cfg = get_config()
    narrator_cfg = cfg.config.get('scene_narrator', {})
    if not narrator_cfg.get('enabled', False):
        logger.info("[SceneNarrator] Disabled in config — skipping init")
        return
    narrator = init_narrator(
        ollama_url=narrator_cfg.get('ollama_url'),
        model=narrator_cfg.get('model'),
        scene_context=narrator_cfg.get('scene_context'),
    )
    narrator.set_frame_source(lambda: camera_manager.get_frame())

    # VLM gesture callback is DISABLED — YOLO Pose keypoints are the sole
    # shake trigger now (faster, no hallucination false-positives).
    # The narrator still toggles between casual/gesture modes for its own
    # scanning loop, but its gesture callback is not wired to the robot.
    gesture_cfg = narrator_cfg.get('gesture', {})
    cooldown = gesture_cfg.get('cooldown_seconds', 10)
    global _GESTURE_COOLDOWN
    _GESTURE_COOLDOWN = cooldown
    logger.info(f"[GesturePose] YOLO Pose is sole shake trigger — cooldown {cooldown}s (VLM gesture callback disabled)")

    # Start in the configured default mode
    global _gesture_enabled
    default_mode = narrator_cfg.get('default_mode', 'casual')
    narrator.set_mode(default_mode)
    _gesture_enabled = (default_mode == 'gesture')
    logger.info(f"[GesturePose] Outstretched hand detection {'ENABLED' if _gesture_enabled else 'DISABLED'} (default mode: {default_mode})")

    narrator.start()
    atexit.register(narrator.stop)


_init_scene_narrator()

@app.route('/api/detection/mode', methods=['GET'])
def get_detection_mode():
    """Report which detector is active: 'yolo' or 'ppe'."""
    pd = get_ppe_detector()
    with _ppe_lock:
        snap = _ppe_last_result
    ppe_info = {'people': 0, 'compliant': 0, 'violations': 0,
                'inference_ms': None, 'age_s': None, 'raw_detections': 0}
    if snap:
        people = snap.get('people', [])
        ppe_info['people'] = len(people)
        ppe_info['compliant'] = sum(1 for p in people if p.get('compliant'))
        ppe_info['violations'] = sum(1 for p in people if not p.get('compliant'))
        ppe_info['inference_ms'] = round(snap.get('inference_ms', 0), 1)
        ppe_info['raw_detections'] = len(snap.get('all_detections', []))
        ts = snap.get('_ts')
        if ts:
            ppe_info['age_s'] = round(time.time() - ts, 1)
    return jsonify({'mode': 'ppe' if _ppe_enabled else 'yolo',
                    'device': pd.device,
                    'yolo_running': web_app.is_running,
                    'ppe_running': _ppe_enabled,
                    'ppe': ppe_info})


@app.route('/api/detection/mode', methods=['POST'])
def set_detection_mode():
    """Switch between YOLO-E and PPE. Only one runs at a time so they never
    contend for the GPU. The video stream is never torn down — /video_feed
    keeps serving and only the overlay source changes, so switching is seamless."""
    global _ppe_enabled, _ppe_last_result, _ppe_thread
    data = request.get_json() or {}
    mode = (data.get('mode') or '').lower()
    if mode not in ('yolo', 'ppe'):
        return jsonify({'status': 'error', 'message': "mode must be 'yolo' or 'ppe'"}), 400

    # Serialize concurrent/double-clicked mode switches so two requests
    # cannot both start a PPE worker or overlap YOLO+PPE on the GPU.
    with _mode_switch_lock:
        if mode == 'ppe':
            # ORDER MATTERS. Start PPE first, then stop YOLO. generate_frames() serves
            # while (is_running or _ppe_enabled); if both are false for even one tick
            # the stream loop exits and the video goes blank until the browser
            # reconnects. Overlapping them by a few milliseconds keeps it seamless.
            if not _ppe_enabled:
                pd = get_ppe_detector()
                try:
                    import torch
                    pd.set_device('cuda' if torch.cuda.is_available() else 'cpu')
                except Exception:
                    pd.set_device('cpu')
                _ppe_enabled = True
                _ppe_thread = threading.Thread(target=_ppe_worker_loop, daemon=True, name='ppe-worker')
                _ppe_thread.start()

            # Now it is safe to tear YOLO down; the camera stays running throughout.
            web_app.is_running = False
            try:
                web_app._stop_detection_feeder()
                # Stop the WORKER too, not just the feeder. Frames already queued keep
                # being processed after is_running flips, and the worker writes its
                # result back into _last_detections AFTER we clear it - so YOLO boxes
                # reappear on top of the PPE overlay. Shutting the worker down first
                # makes the clear below final. The queue is drained on next start.
                web_app.shutdown_detection_worker()
            except Exception as e:
                logger.warning("[Mode] detection shutdown: %s", e)
            with web_app._detection_lock:
                web_app._last_detections = []
            logger.info("[Mode] -> PPE")
        else:
            # Same ordering rule in reverse: bring YOLO up before dropping PPE so
            # has_activity never goes false and the stream never breaks.
            if not web_app.is_running:
                web_app.is_running = True
                web_app._ensure_detection_worker()
                web_app._start_detection_feeder()
            _ppe_enabled = False
            with _ppe_lock:
                _ppe_last_result = None
            logger.info("[Mode] -> YOLO")

    return jsonify({'status': 'success', 'mode': mode,
                    'device': get_ppe_detector().device})


@app.route('/api/gesture', methods=['GET'])
def get_gesture_state():
    gd = get_gesture_detector()
    return jsonify({
        'enabled': _gesture_enabled,
        'triggers': _gesture_count,
        'cooldown_seconds': _GESTURE_COOLDOWN,
        'cooldown_remaining': max(0.0, round(_GESTURE_COOLDOWN - (time.time() - _gesture_last_trigger_ts), 1)),
        'last_reason': get_hand_detector().last.get('reason'),
        'last_area_frac': get_hand_detector().last.get('area_frac'),
        'last_confidence': get_hand_detector().last.get('confidence'),
        'last_fingers': get_hand_detector().last.get('fingers'),
        'device': get_hand_detector().device,
        'tuning': get_hand_detector().cfg,
    })


@app.route('/api/gesture', methods=['POST'])
def set_gesture_state():
    """Arm or disarm the outstretched-hand -> shake behaviour.

    Explicit and independent of the scene narrator, because this fires a real
    physical movement on the robot.
    """
    global _gesture_enabled
    data = request.get_json() or {}
    if 'enabled' in data:
        _gesture_enabled = bool(data['enabled'])
    # Optional live tuning so thresholds can be dialled in with a hand in frame.
    hd = get_hand_detector()
    for k in ('min_area_frac', 'center_band', 'min_conf', 'require_open', 'min_fingers'):
        if k in data:
            hd.cfg[k] = data[k]
    logger.info("[Gesture] %s by operator; tuning=%s",
                'ARMED' if _gesture_enabled else 'DISARMED', hd.cfg)
    return jsonify({'status': 'success', 'enabled': _gesture_enabled, 'tuning': hd.cfg})


if __name__ == '__main__':
    print("Starting Computer Vision Object Detector Web App")
    print("Open your browser and go to: http://0.0.0.0:8000")
    # Debug mode disabled to prevent double camera initialization (Flask spawns child process in debug mode)
    app.run(debug=False, host='0.0.0.0', port=8000, threaded=True, use_reloader=False)
