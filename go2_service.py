#!/usr/bin/env python3
"""
GO2 Service - Optimized for Performance
Provides battery, video, and commands via HTTP
"""
import asyncio, sys, threading, queue, cv2, time
from flask import Flask, jsonify, Response, request
from flask_cors import CORS

sys.path.insert(0, '/home/unitree/.local/lib/python3.8/site-packages')
from unitree_webrtc_connect.webrtc_driver import UnitreeWebRTCConnection, WebRTCConnectionMethod  
from unitree_webrtc_connect.constants import RTC_TOPIC, SPORT_CMD
from aiortc import MediaStreamTrack

app = Flask(__name__)
CORS(app)

battery_state = {'soc': None, 'voltage': None, 'current': None, 'connected': False}
latest_frame = None
frame_lock = threading.Lock()
command_queue = queue.Queue()
command_results = {}
result_lock = threading.Lock()

COMMAND_MAP = {
    'stand': SPORT_CMD['StandUp'],
    'crouch': SPORT_CMD['StandDown'],
    'sit': SPORT_CMD['Sit'],
    'shake': SPORT_CMD['Hello']
}

async def recv_camera_stream(track: MediaStreamTrack):
    global latest_frame
    while True:
        try:
            frame = await track.recv()
            img = frame.to_ndarray(format='bgr24')
            with frame_lock:
                latest_frame = img
        except: 
            await asyncio.sleep(0.05)

async def robot_loop():
    global battery_state, command_results
    conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, ip='192.168.50.75')
    await conn.connect()
    battery_state['connected'] = True
    
    conn.video.switchVideoChannel(True)
    conn.video.add_track_callback(recv_camera_stream)
    
    def lowstate_callback(message):
        data = message['data']
        bms = data['bms_state']
        battery_state['soc'] = bms['soc']
        battery_state['voltage'] = data['power_v']
        battery_state['current'] = bms['current']
    
    conn.datachannel.pub_sub.subscribe(RTC_TOPIC['LOW_STATE'], lowstate_callback)
    
    # 30Hz command processing loop
    while True: 
        try:
            if not command_queue.empty():
                cmd_id, cmd_api_id, result_id = command_queue.get_nowait()
                try:
                    resp = await conn.datachannel.pub_sub.publish_request_new(
                        RTC_TOPIC['SPORT_MOD'], {'api_id': cmd_api_id}
                    )
                    success = resp.get('data', {}).get('header', {}).get('status', {}).get('code', 1) == 0
                    with result_lock:
                        command_results[result_id] = {'success': success}
                except Exception as e:
                    with result_lock:
                        command_results[result_id] = {'success': False, 'error': str(e)}
        except:
            pass
        await asyncio.sleep(0.03)  # 30Hz loop

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
        while True:
            with frame_lock:
                if latest_frame is not None:
                    ret, buffer = cv2.imencode('.jpg', latest_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    if ret:
                        yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            time.sleep(0.03)  # ~30 FPS
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
    
    # Wait for result with timeout
    start_time = time.time()
    while time.time() - start_time < 3.0:
        with result_lock:
            if result_id in command_results:
                return jsonify(command_results.pop(result_id))
        time.sleep(0.05)
    
    return jsonify({'success': False, 'message': 'Timeout'}), 504

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, threaded=True)
