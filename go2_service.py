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
move_queue = queue.Queue()
move_results = {}
move_lock = threading.Lock()
_move_state = {'balance_ready': False}
standing_heartbeat_queue = queue.Queue()

COMMAND_MAP = {
    'stand': SPORT_CMD['StandUp'],
    'crouch': SPORT_CMD['StandDown'],
    'sit': SPORT_CMD['Sit'],
    'shake': SPORT_CMD['Hello']
}

KEEPALIVE_COMMANDS = {'sit', 'shake'}
# 'stand' intentionally excluded — keepalive pings send set_motion_mode('normal')
# which conflicts with BalanceStand posture and causes the robot to fall over.
# Standing commands STOP the keepalive instead (see handle_command).
KEEPALIVE_STOP_COMMANDS = {'stand', 'crouch'}  # commands that should halt keepalive
KEEPALIVE_INTERVAL_SECONDS = 30   # increased from 20 — less aggressive pinging

# Standing posture needs a sport-level refresh, not a motion-switcher keepalive.
# Field logs show the robot can stay up for roughly 10 minutes after StandUp and
# then enter a red-light fault/fall when no further WebRTC sport traffic is sent.
# Re-selecting MOTION_SWITCHER "normal" while standing previously caused falls, so
# this heartbeat intentionally re-sends the posture command on SPORT_MOD instead.
# Five minutes keeps the refresh well inside the observed firmware timeout while
# avoiding high-rate command churn.
STANDING_HEARTBEAT_INTERVAL_SECONDS = 300
REMOTE_ACTIVITY_TIMEOUT = 5.0  # seconds of silence before assuming remote released control
REMOTE_AXIS_THRESHOLD = 0.05
LENIENT_STATUS_CODES = {
    'sit': {-1},
    'shake': {-1},
}
COMMAND_RESULT_TIMEOUT = 8.0

# --- Robot safety state ---
_robot_busy_lock = threading.Lock()
_robot_busy = False          # True while a sport command is in-flight
_robot_last_cmd_ts = 0.0     # timestamp of last sport command sent
_ROBOT_CMD_MIN_GAP = 2.0     # minimum seconds between sport commands
_robot_posture = 'idle'      # tracks current posture: 'idle', 'standing', 'sitting'
_robot_posture_lock = threading.Lock()
JPEG_QUALITY = int(os.environ.get('GO2_JPEG_QUALITY', '80'))
JPEG_ENCODE_PARAMS = [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]

keepalive_lock = threading.Lock()
keepalive_stop_event = threading.Event()
keepalive_thread = None
keepalive_active = False

standing_heartbeat_lock = threading.Lock()
standing_heartbeat_stop_event = threading.Event()
standing_heartbeat_thread = None
standing_heartbeat_active = False

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
    """Queue a motion mode ping without requiring a response.
    Skips if robot is standing, busy, or recently executed a sport command.
    """
    with _robot_posture_lock:
        posture = _robot_posture
    if posture == 'standing':
        print(f"[KeepAlive] Skipping ping ({source}) — robot is standing", flush=True)
        return
    with _robot_busy_lock:
        if _robot_busy:
            print(f"[KeepAlive] Skipping ping ({source}) — robot busy", flush=True)
            return
        gap = time.time() - _robot_last_cmd_ts
        if gap < _ROBOT_CMD_MIN_GAP:
            print(f"[KeepAlive] Skipping ping ({source}) — too soon after command ({gap:.1f}s)", flush=True)
            return
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
    # Send one initial mode ping to ensure we're in 'normal'
    enqueue_motion_mode_ping(f"start:{trigger_source}")

    while True:
        if keepalive_stop_event.wait(KEEPALIVE_INTERVAL_SECONDS):
            break
        if remote_is_actively_controlling():
            print("[KeepAlive] Remote activity detected; stopping keepalive loop", flush=True)
            break
        # Safety: skip mode ping if a sport command is currently in-flight
        with _robot_busy_lock:
            busy = _robot_busy
        if busy:
            print("[KeepAlive] Robot busy with command — skipping mode ping", flush=True)
            continue
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


def standing_sport_heartbeat_worker(trigger_source):
    global standing_heartbeat_active, standing_heartbeat_thread
    print(f"[StandHeartbeat] Sport heartbeat started via {trigger_source}", flush=True)

    while True:
        if standing_heartbeat_stop_event.wait(STANDING_HEARTBEAT_INTERVAL_SECONDS):
            break

        with _robot_posture_lock:
            posture = _robot_posture
        if posture != 'standing':
            print("[StandHeartbeat] Posture no longer standing; stopping", flush=True)
            break

        if remote_is_actively_controlling():
            print("[StandHeartbeat] Remote activity detected; stopping", flush=True)
            break

        with _robot_busy_lock:
            if _robot_busy:
                print("[StandHeartbeat] Robot busy with command — skipping this interval", flush=True)
                continue

        try:
            standing_heartbeat_queue.put(('StandUp', SPORT_CMD['StandUp']))
            print("[StandHeartbeat] Queued SPORT_MOD StandUp refresh", flush=True)
        except Exception as exc:
            print(f"[StandHeartbeat] Failed to queue refresh: {exc}", flush=True)

    with standing_heartbeat_lock:
        standing_heartbeat_active = False
        standing_heartbeat_thread = None
        standing_heartbeat_stop_event.clear()

    print("[StandHeartbeat] Sport heartbeat stopped", flush=True)


def start_standing_sport_heartbeat(trigger_source):
    global standing_heartbeat_thread, standing_heartbeat_active
    with standing_heartbeat_lock:
        if standing_heartbeat_active:
            print(f"[StandHeartbeat] Loop already active, skipping trigger {trigger_source}", flush=True)
            return False
        standing_heartbeat_stop_event.clear()
        standing_heartbeat_thread = threading.Thread(
            target=standing_sport_heartbeat_worker,
            args=(trigger_source,),
            daemon=True
        )
        standing_heartbeat_active = True
        print(f"[StandHeartbeat] Spawning sport heartbeat thread via {trigger_source}", flush=True)
        standing_heartbeat_thread.start()
        return True


def stop_standing_sport_heartbeat(reason=''):
    with standing_heartbeat_lock:
        if not standing_heartbeat_active:
            return False
        print(f"[StandHeartbeat] Stop requested ({reason})", flush=True)
        standing_heartbeat_stop_event.set()
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
            conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip='192.168.123.161')
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
    global battery_state, command_results, _robot_busy, _robot_last_cmd_ts

    while True:
        conn = await establish_connection_with_retry()
        try:
            # Ensure motion mode is set to 'normal' — but NOT if robot is standing
            # (sending mode change while standing causes safety fault / red light)
            with _robot_posture_lock:
                posture = _robot_posture
            if posture == 'standing':
                print(f"[Connect] Skipping initial set_motion_mode — robot is standing", flush=True)
            else:
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
                global _robot_posture
                data = message['data']
                bms = data['bms_state']
                battery_state['soc'] = bms['soc']
                battery_state['voltage'] = data['power_v']
                battery_state['current'] = bms['current']
                remote_data = data.get('wireless_remote') or data.get('wirelessRemote')
                if remote_data and detect_remote_activity(remote_data):
                    mark_remote_activity()
                    stop_motion_keepalive('remote takeover detected via wireless remote input')
                    stop_standing_sport_heartbeat('remote takeover detected via wireless remote input')
                    # Remote operator may change posture — clear standing guard
                    with _robot_posture_lock:
                        if _robot_posture == 'standing':
                            _robot_posture = 'idle'
                            print("[Posture] → idle (remote takeover)", flush=True)
            
            conn.datachannel.pub_sub.subscribe(RTC_TOPIC['LOW_STATE'], lowstate_callback)
            
            # 30Hz command processing loop
            while True: 
                try:
                    try:
                        mode_name, result_id = motion_mode_queue.get_nowait()
                        # Final safety gate: drop keepalive pings if robot is standing
                        with _robot_posture_lock:
                            posture = _robot_posture
                        if posture == 'standing' and result_id is None:
                            # result_id is None → this is a keepalive ping, not an explicit API call
                            print(f"[Safety] Dropping mode ping '{mode_name}' — robot is standing", flush=True)
                            raise queue.Empty  # skip to next iteration
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
                    except queue.Empty:
                        pass

                    try:
                        cmd_id, cmd_api_id, result_id = command_queue.get_nowait()
                        _move_state['balance_ready'] = False

                        # --- Safety: mark robot busy and enforce minimum gap ---
                        with _robot_busy_lock:
                            _robot_busy = True
                        try:
                            # Verify motion mode is 'normal' before sending sport cmd
                            try:
                                mode_resp = await set_motion_mode(conn, 'normal')
                                mode_status = mode_resp.get('data', {}).get('header', {}).get('status', {})
                                mode_code = mode_status.get('code', 1)
                                if mode_code != 0:
                                    msg = mode_status.get('message') or mode_status.get('msg') or ''
                                    print(f"[Command] Mode check returned code {mode_code}: {msg} — proceeding cautiously", flush=True)
                            except Exception as mode_err:
                                print(f"[Command] Mode verify failed: {mode_err} — proceeding anyway", flush=True)

                            # Small pause to let mode settle before sport command
                            await asyncio.sleep(0.1)

                            resp = await conn.datachannel.pub_sub.publish_request_new(
                                RTC_TOPIC['SPORT_MOD'], {'api_id': cmd_api_id}
                            )
                            status = resp.get('data', {}).get('header', {}).get('status', {})
                            code = status.get('code', 1)
                            success = (code == 0) or (code in LENIENT_STATUS_CODES.get(cmd_id, set()))
                            if code in LENIENT_STATUS_CODES.get(cmd_id, set()) and code != 0:
                                print(f"[Command] {cmd_id} returned tolerated code {code}", flush=True)
                            message = status.get('message') or status.get('msg') or ''

                            # If sport command failed with an unexpected code, attempt recovery
                            if not success and code not in LENIENT_STATUS_CODES.get(cmd_id, set()):
                                print(f"[Command] {cmd_id} FAILED code={code} msg='{message}' — attempting RecoveryStand", flush=True)
                                try:
                                    await conn.datachannel.pub_sub.publish_request_new(
                                        RTC_TOPIC['SPORT_MOD'], {'api_id': SPORT_CMD.get('RecoveryStand', SPORT_CMD.get('StandUp'))}
                                    )
                                    print(f"[Command] RecoveryStand sent after {cmd_id} failure", flush=True)
                                except Exception as recovery_err:
                                    print(f"[Command] RecoveryStand also failed: {recovery_err}", flush=True)

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
                        finally:
                            with _robot_busy_lock:
                                _robot_busy = False
                                _robot_last_cmd_ts = time.time()
                    except queue.Empty:
                        pass

                    try:
                        vx, vy, vyaw, result_id = move_queue.get_nowait()
                        try:
                            if not _move_state['balance_ready']:
                                await conn.datachannel.pub_sub.publish_request_new(
                                    RTC_TOPIC['SPORT_MOD'], {'api_id': SPORT_CMD['BalanceStand']}
                                )
                                _move_state['balance_ready'] = True
                            resp = await conn.datachannel.pub_sub.publish_request_new(
                                RTC_TOPIC['SPORT_MOD'],
                                {'api_id': SPORT_CMD['Move'], 'parameter': {'x': vx, 'y': vy, 'z': vyaw}}
                            )
                            status = resp.get('data', {}).get('header', {}).get('status', {})
                            code = status.get('code', 1)
                            with move_lock:
                                move_results[result_id] = {'success': True, 'code': code}
                        except Exception as e:
                            with move_lock:
                                move_results[result_id] = {'success': False, 'error': str(e)}
                    except queue.Empty:
                        pass

                    try:
                        heartbeat_name, heartbeat_api_id = standing_heartbeat_queue.get_nowait()
                        with _robot_posture_lock:
                            posture = _robot_posture
                        if posture != 'standing':
                            print(f"[StandHeartbeat] Dropping {heartbeat_name} — posture is {posture}", flush=True)
                            continue
                        with _robot_busy_lock:
                            if _robot_busy:
                                print(f"[StandHeartbeat] Dropping {heartbeat_name} — robot busy", flush=True)
                                continue
                            _robot_busy = True
                        try:
                            resp = await conn.datachannel.pub_sub.publish_request_new(
                                RTC_TOPIC['SPORT_MOD'], {'api_id': heartbeat_api_id}
                            )
                            status = resp.get('data', {}).get('header', {}).get('status', {})
                            code = status.get('code', 1)
                            msg = status.get('message') or status.get('msg') or ''
                            if code == 0:
                                print(f"[StandHeartbeat] {heartbeat_name} refresh accepted", flush=True)
                            else:
                                print(f"[StandHeartbeat] {heartbeat_name} refresh returned code={code} msg='{msg}'", flush=True)
                        except Exception as heartbeat_error:
                            print(f"[StandHeartbeat] {heartbeat_name} refresh failed: {heartbeat_error}", flush=True)
                        finally:
                            with _robot_busy_lock:
                                _robot_busy = False
                    except queue.Empty:
                        pass
                except Exception as loop_error:
                    print(f"[Loop] Error processing commands: {loop_error}", flush=True)
                await asyncio.sleep(0.03)
        except Exception as connection_error:
            battery_state['connected'] = False
            stop_standing_sport_heartbeat('WebRTC session lost')
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

    # --- Safety: reject if robot is already executing a command ---
    with _robot_busy_lock:
        if _robot_busy:
            print(f"[Command] REJECTED '{cmd_name}' — robot busy with another command", flush=True)
            return jsonify({'success': False, 'message': 'Robot busy — wait for current command to finish'}), 429
        # Also enforce minimum gap between commands
        gap = time.time() - _robot_last_cmd_ts
        if gap < _ROBOT_CMD_MIN_GAP:
            remaining = _ROBOT_CMD_MIN_GAP - gap
            print(f"[Command] REJECTED '{cmd_name}' — too soon after last command ({gap:.1f}s < {_ROBOT_CMD_MIN_GAP}s)", flush=True)
            return jsonify({'success': False, 'message': f'Command cooldown — wait {remaining:.1f}s'}), 429

    # Track posture so we can guard against disruptive mode changes
    global _robot_posture
    with _robot_posture_lock:
        if cmd_name == 'stand':
            _robot_posture = 'standing'
            print(f"[Posture] → standing", flush=True)
        else:
            # Any non-stand command (crouch, sit, shake) means the robot
            # is transitioning out of standing posture — safe to allow pings again
            _robot_posture = 'idle'
            print(f"[Posture] → idle ({cmd_name})", flush=True)

    result_id = f'{cmd_name}_{time.time()}'
    command_queue.put((cmd_name, COMMAND_MAP[cmd_name], result_id))
    if cmd_name == 'stand':
        start_standing_sport_heartbeat('stand command issued')
    else:
        stop_standing_sport_heartbeat(f'{cmd_name} command issued')

    if cmd_name in KEEPALIVE_STOP_COMMANDS:
        stop_motion_keepalive(f'{cmd_name} command issued — suppressing keepalive pings')
    elif cmd_name in KEEPALIVE_COMMANDS:
        start_motion_keepalive_if_needed(cmd_name)

    # Wait for result with timeout
    start_time = time.time()
    while time.time() - start_time < COMMAND_RESULT_TIMEOUT:
        with result_lock:
            if result_id in command_results:
                result = command_results.pop(result_id)
                if cmd_name == 'stand':
                    if result.get('success'):
                        start_standing_sport_heartbeat('stand command accepted')
                    else:
                        stop_standing_sport_heartbeat('stand command failed')
                else:
                    stop_standing_sport_heartbeat(f'{cmd_name} command issued')
                return jsonify(result)
        time.sleep(0.05)

    if cmd_name == 'stand':
        stop_standing_sport_heartbeat('stand command timed out')
    return jsonify({'success': False, 'message': 'Timeout'}), 504

@app.route('/move', methods=['POST'])
def handle_move():
    # Safety: reject move commands while robot is in standing posture hold
    # — move path sends BalanceStand which conflicts with StandUp
    with _robot_posture_lock:
        posture = _robot_posture
    if posture == 'standing':
        return jsonify({'success': False, 'message': 'Cannot move — robot is in standing posture. Send crouch first.'}), 409

    data = request.get_json()
    vx = float(data.get('vx', 0))
    vy = float(data.get('vy', 0))
    vyaw = float(data.get('vyaw', 0))

    result_id = f'move_{time.time()}'
    move_queue.put((vx, vy, vyaw, result_id))

    start_time = time.time()
    while time.time() - start_time < 3.0:
        with move_lock:
            if result_id in move_results:
                return jsonify(move_results.pop(result_id))
        time.sleep(0.05)

    return jsonify({'success': False, 'message': 'Timeout'}), 504

@app.route('/stop', methods=['POST'])
def handle_stop():
    # Safety: if robot is standing (posture hold), don't send move commands
    # — the move path sends BalanceStand which conflicts with StandUp posture
    global _robot_posture
    with _robot_posture_lock:
        posture = _robot_posture
    if posture == 'standing':
        stop_standing_sport_heartbeat('stop command issued')
        with _robot_posture_lock:
            _robot_posture = 'idle'
            print("[Posture] → idle (stop)", flush=True)
        print("[Stop] Ignored — robot is in standing posture hold", flush=True)
        return jsonify({'success': True, 'message': 'No-op — robot is standing'})

    result_id = f'stop_{time.time()}'
    move_queue.put((0, 0, 0, result_id))

    start_time = time.time()
    while time.time() - start_time < 3.0:
        with move_lock:
            if result_id in move_results:
                return jsonify(move_results.pop(result_id))
        time.sleep(0.05)

    return jsonify({'success': True, 'message': 'Stop sent'})

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
