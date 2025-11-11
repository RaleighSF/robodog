#!/usr/bin/env python3
"""
GO2 Service - Optimized for Performance
Provides battery, video, and commands via HTTP
"""
import asyncio, sys, threading, queue, cv2, time, struct, os
from flask import Flask, jsonify, Response, request
from flask_cors import CORS

sys.path.insert(0, '/home/unitree/.local/lib/python3.8/site-packages')
os.environ.setdefault('OPENCV_FFMPEG_CAPTURE_OPTIONS', 'loglevel;quiet')
try:
    cv2.setLogLevel(cv2.LOG_LEVEL_SILENT)
except AttributeError:
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
    except Exception:
        pass
from unitree_webrtc_connect.webrtc_driver import UnitreeWebRTCConnection, WebRTCConnectionMethod  
from unitree_webrtc_connect.constants import RTC_TOPIC, SPORT_CMD
try:
    import av
    av.logging.set_level(av.logging.QUIET)
    av.logging.set_libav_level(av.logging.QUIET)
    av.logging.set_skip_repeated(True)
except Exception:
    av = None
from aiortc import MediaStreamTrack


def suppress_swscale_logs():
    """Redirect C-level stderr to filter noisy swscaler warnings."""
    suppress = b"No accelerated colorspace conversion found from yuv420p to bgr24"
    def redirect_stream(fd):
        try:
            original_fd = os.dup(fd)
            read_fd, write_fd = os.pipe()
            os.dup2(write_fd, fd)
            os.close(write_fd)
        except OSError:
            return

        def pump():
            with os.fdopen(read_fd, 'rb', buffering=0) as reader, os.fdopen(original_fd, 'wb', buffering=0) as writer:
                while True:
                    data = reader.readline()
                    if not data:
                        break
                    if suppress in data:
                        continue
                    writer.write(data)

        threading.Thread(target=pump, daemon=True).start()

    redirect_stream(1)
    redirect_stream(2)


suppress_swscale_logs()

app = Flask(__name__)
CORS(app)

battery_state = {'soc': None, 'voltage': None, 'current': None, 'connected': False}
latest_frame = None
latest_jpeg = None
frame_lock = threading.Lock()
frame_counter = 0
command_queue = queue.Queue()
command_results = {}
result_lock = threading.Lock()
encoding_queue = queue.Queue(maxsize=2)
motion_mode_queue = queue.Queue()
motion_mode_results = {}
motion_mode_lock = threading.Lock()

COMMAND_MAP = {
    'stand': SPORT_CMD['StandUp'],
    'crouch': SPORT_CMD['StandDown'],
    'sit': SPORT_CMD['Sit'],
    'shake': SPORT_CMD['Hello']
}

KEEPALIVE_COMMANDS = {'stand', 'sit', 'shake'}
KEEPALIVE_INTERVAL_SECONDS = 20
REMOTE_ACTIVITY_TIMEOUT = 5.0  # seconds of silence before assuming remote released control
REMOTE_AXIS_THRESHOLD = 0.05
LENIENT_STATUS_CODES = {
    'sit': {-1},
    'shake': {-1},
}
COMMAND_RESULT_TIMEOUT = 8.0
JPEG_QUALITY = int(os.environ.get('GO2_JPEG_QUALITY', '80'))
JPEG_ENCODE_PARAMS = [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]

keepalive_lock = threading.Lock()
keepalive_stop_event = threading.Event()
keepalive_thread = None
keepalive_active = False

remote_activity_lock = threading.Lock()
remote_last_active_ts = 0.0


def frame_encoder_worker():
    global latest_jpeg, frame_counter
    while True:
        frame = encoding_queue.get()
        try:
            ret, buffer = cv2.imencode('.jpg', frame, JPEG_ENCODE_PARAMS)
            if ret:
                jpeg_bytes = buffer.tobytes()
                with frame_lock:
                    latest_jpeg = jpeg_bytes
                    frame_counter += 1
        except Exception as exc:
            print(f"[Encoder] Failed to encode frame: {exc}", flush=True)
        finally:
            encoding_queue.task_done()


threading.Thread(target=frame_encoder_worker, daemon=True).start()


def enqueue_motion_mode_ping(source='keepalive'):
    """Queue a motion mode ping without requiring a response."""
    try:
        motion_mode_queue.put(('normal', None))
        print(f"[KeepAlive] Queued 'normal' ping ({source})", flush=True)
    except Exception as exc:
        print(f"[KeepAlive] Failed to queue ping ({source}): {exc}", flush=True)


def remote_is_actively_controlling():
    with remote_activity_lock:
        if remote_last_active_ts == 0.0:
            return False
        return (time.time() - remote_last_active_ts) < REMOTE_ACTIVITY_TIMEOUT


def mark_remote_activity():
    global remote_last_active_ts
    with remote_activity_lock:
        remote_last_active_ts = time.time()


def detect_remote_activity(remote_data):
    """Best-effort detection of wireless remote activity based on joystick/button input."""
    if remote_data is None:
        return False

    try:
        remote_bytes = bytes(remote_data)
    except (TypeError, ValueError):
        try:
            remote_bytes = bytes(int(x) & 0xFF for x in remote_data)
        except Exception:
            return False

    if len(remote_bytes) < 24:
        return False

    buttons_active = remote_bytes[2] != 0 or remote_bytes[3] != 0
    axes_active = False

    try:
        axes = []
        for offset in (4, 8, 12, 20):
            segment = remote_bytes[offset:offset + 4]
            if len(segment) < 4:
                continue
            axes.append(struct.unpack('<f', segment)[0])
        axes_active = any(abs(val) > REMOTE_AXIS_THRESHOLD for val in axes)
    except Exception:
        pass

    return buttons_active or axes_active


def motion_keepalive_worker(trigger_source):
    global keepalive_active, keepalive_thread
    print(f"[KeepAlive] Motion keepalive started via {trigger_source}", flush=True)
    enqueue_motion_mode_ping(f"start:{trigger_source}")

    while True:
        if keepalive_stop_event.wait(KEEPALIVE_INTERVAL_SECONDS):
            break
        if remote_is_actively_controlling():
            print("[KeepAlive] Remote activity detected; stopping keepalive loop", flush=True)
            break
        enqueue_motion_mode_ping('interval')

    with keepalive_lock:
        keepalive_active = False
        keepalive_thread = None
        keepalive_stop_event.clear()

    print("[KeepAlive] Motion keepalive stopped", flush=True)


def start_motion_keepalive_if_needed(trigger_source):
    global keepalive_thread, keepalive_active
    with keepalive_lock:
        if keepalive_active:
            print(f"[KeepAlive] Loop already active, skipping trigger {trigger_source}", flush=True)
            return False
        keepalive_stop_event.clear()
        keepalive_thread = threading.Thread(
            target=motion_keepalive_worker,
            args=(trigger_source,),
            daemon=True
        )
        keepalive_active = True
        print(f"[KeepAlive] Spawning keepalive thread via {trigger_source}", flush=True)
        keepalive_thread.start()
        return True


def stop_motion_keepalive(reason=''):
    with keepalive_lock:
        if not keepalive_active:
            return False
        print(f"[KeepAlive] Stop requested ({reason})", flush=True)
        keepalive_stop_event.set()
        return True


async def set_motion_mode(conn, mode_name='normal'):
    """Ensure the GO2 motion controller is in a desired mode."""
    return await conn.datachannel.pub_sub.publish_request_new(
        RTC_TOPIC['MOTION_SWITCHER'],
        {
            'api_id': 1002,
            'parameter': {'name': mode_name}
        }
    )

async def recv_camera_stream(track: MediaStreamTrack):
    global latest_frame
    while True:
        try:
            frame = await track.recv()
            img = frame.to_ndarray(format='bgr24')
            with frame_lock:
                latest_frame = img
            try:
                encoding_queue.put_nowait(img)
            except queue.Full:
                pass
        except: 
            await asyncio.sleep(0.05)


async def establish_connection_with_retry():
    """Persistently try to bring up the WebRTC session so the API heals after reboots."""
    attempt = 0
    while True:
        attempt += 1
        try:
            conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip='192.168.50.75')
            await conn.connect()
            battery_state['connected'] = True
            if attempt > 1:
                print(f"[Connect] Recovered connection on attempt {attempt}", flush=True)
            return conn
        except Exception as connect_error:
            battery_state['connected'] = False
            wait_time = min(5 * attempt, 30)
            print(f"[Connect] Attempt {attempt} failed: {connect_error}. Retry in {wait_time}s", flush=True)
            await asyncio.sleep(wait_time)

async def robot_loop():
    global battery_state, command_results

    while True:
        conn = await establish_connection_with_retry()
        try:
            # Ensure motion mode is set to 'normal' so sport commands are accepted
            try:
                resp = await set_motion_mode(conn, 'normal')
                status = resp.get('data', {}).get('header', {}).get('status', {})
                msg = status.get('message') or status.get('msg') or ''
                print(f"Motion mode set response: code={status.get('code')} msg='{msg}'")
            except Exception as motion_error:
                print(f"Failed to set motion mode: {motion_error}")
            
            conn.video.switchVideoChannel(True)
            conn.video.add_track_callback(recv_camera_stream)
            
            def lowstate_callback(message):
                data = message['data']
                bms = data['bms_state']
                battery_state['soc'] = bms['soc']
                battery_state['voltage'] = data['power_v']
                battery_state['current'] = bms['current']
                remote_data = data.get('wireless_remote') or data.get('wirelessRemote')
                if remote_data and detect_remote_activity(remote_data):
                    mark_remote_activity()
                    stop_motion_keepalive('remote takeover detected via wireless remote input')
            
            conn.datachannel.pub_sub.subscribe(RTC_TOPIC['LOW_STATE'], lowstate_callback)
            
            # 30Hz command processing loop
            while True: 
                try:
                    if not motion_mode_queue.empty():
                        mode_name, result_id = motion_mode_queue.get_nowait()
                        try:
                            resp = await set_motion_mode(conn, mode_name)
                            status = resp.get('data', {}).get('header', {}).get('status', {})
                            success = status.get('code', 1) == 0
                            message = status.get('message') or status.get('msg') or f"Requested {mode_name}"
                            if result_id is not None:
                                with motion_mode_lock:
                                    motion_mode_results[result_id] = {
                                        'success': success,
                                        'message': message,
                                        'raw_status': status,
                                        'response': resp
                                    }
                        except Exception as e:
                            if result_id is not None:
                                with motion_mode_lock:
                                    motion_mode_results[result_id] = {'success': False, 'error': str(e)}

                    if not command_queue.empty():
                        cmd_id, cmd_api_id, result_id = command_queue.get_nowait()
                        try:
                            resp = await conn.datachannel.pub_sub.publish_request_new(
                                RTC_TOPIC['SPORT_MOD'], {'api_id': cmd_api_id}
                            )
                            status = resp.get('data', {}).get('header', {}).get('status', {})
                            code = status.get('code', 1)
                            success = (code == 0) or (code in LENIENT_STATUS_CODES.get(cmd_id, set()))
                            if code in LENIENT_STATUS_CODES.get(cmd_id, set()) and code != 0:
                                print(f"[Command] {cmd_id} returned tolerated code {code}", flush=True)
                            message = status.get('message') or status.get('msg') or ''
                            with result_lock:
                                command_results[result_id] = {
                                    'success': success,
                                    'message': message,
                                    'raw_status': status,
                                    'response': resp
                                }
                        except Exception as e:
                            with result_lock:
                                command_results[result_id] = {'success': False, 'error': str(e)}
                except Exception as loop_error:
                    print(f"[Loop] Error processing commands: {loop_error}", flush=True)
                await asyncio.sleep(0.03)  # 30Hz loop
        except Exception as connection_error:
            battery_state['connected'] = False
            print(f"[Connect] Connection lost: {connection_error}", flush=True)
            await asyncio.sleep(5)
        finally:
            try:
                conn.video.switchVideoChannel(False)
            except Exception:
                pass

def start_robot_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(robot_loop())

threading.Thread(target=start_robot_thread, daemon=True).start()

@app.route('/battery')
def battery():
    return jsonify(battery_state)

@app.route('/video_feed')
def video_feed():
    def generate():
        client_frame_id = -1
        while True:
            with frame_lock:
                jpeg = latest_jpeg
                server_frame_id = frame_counter
            if jpeg is not None and server_frame_id != client_frame_id:
                client_frame_id = server_frame_id
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + jpeg + b'\r\n')
            else:
                time.sleep(0.01)
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/status')
def status():
    with frame_lock:
        frame_available = latest_frame is not None
    
    return jsonify({
        'connected': battery_state['connected'],
        'battery_soc': battery_state['soc'],
        'has_video': frame_available
    })

@app.route('/command', methods=['POST'])
def handle_command():
    data = request.get_json()
    cmd_name = data.get('command')
    
    if not cmd_name or cmd_name not in COMMAND_MAP:
        return jsonify({'success': False, 'message': 'Invalid command'}), 400
    
    result_id = f'{cmd_name}_{time.time()}'
    command_queue.put((cmd_name, COMMAND_MAP[cmd_name], result_id))

    if cmd_name in KEEPALIVE_COMMANDS:
        start_motion_keepalive_if_needed(cmd_name)
    elif cmd_name == 'crouch':
        stop_motion_keepalive('crouch command issued')
    
    # Wait for result with timeout
    start_time = time.time()
    while time.time() - start_time < COMMAND_RESULT_TIMEOUT:
        with result_lock:
            if result_id in command_results:
                return jsonify(command_results.pop(result_id))
        time.sleep(0.05)
    
    return jsonify({'success': False, 'message': 'Timeout'}), 504

@app.route('/motion_mode', methods=['POST'])
def set_motion_mode_route():
    data = request.get_json() or {}
    mode = data.get('mode', 'normal')

    if not isinstance(mode, str):
        return jsonify({'success': False, 'message': 'Mode must be a string'}), 400

    result_id = f'motion_{mode}_{time.time()}'
    motion_mode_queue.put((mode, result_id))

    start_time = time.time()
    while time.time() - start_time < 3.0:
        with motion_mode_lock:
            if result_id in motion_mode_results:
                return jsonify(motion_mode_results.pop(result_id))
        time.sleep(0.05)

    return jsonify({'success': False, 'message': 'Timeout'}), 504

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, threaded=True)
