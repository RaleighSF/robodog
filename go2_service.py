#!/usr/bin/env python3
"""
GO2 Service (DDS edition) — Watch Dog's robot link on the dog's Orin.

Firmware 1.1.15 moved the Go2 to per-device-keyed WebRTC, so this service
follows the path Azimuth proved on the same robot (azimuth repo,
edge/transport.py DDSTransport):

  * Commands + telemetry over DDS on the robot's wire: rclpy publishes
    unitree_api/Request on /api/sport/request, replies are matched by
    header.identity.id on /api/sport/response; battery from /lf/lowstate,
    liveness + body height from /lf/sportmodestate. Lease id 0: Watch Dog
    and Azimuth never run at the same time (azimuth-edge.service declares
    Conflicts=go2_service), so nobody else holds the sport lease.
  * Video only over WebRTC (library 2.2.0, per-device AES key from
    GO2_AES_KEY): the front camera has no usable DDS framing yet.

Same HTTP contract as the old WebRTC service on :5001, so the dashboard and
the auto-arm supervisor are unchanged:
  GET /status /battery /video_feed   POST /command /move /stop /motion_mode

Runs inside the watchdog-go2 container (FROM azimuth-edge:dev: ROS 2 Humble,
unitree_api/unitree_go, WebRTC 2.2.0). See deploy/orin/.
"""
import asyncio
import json
import os
import queue
import threading
import time

import cv2
from flask import Flask, Response, jsonify, request

ROBOT_IP = os.environ.get("GO2_ROBOT_IP", "192.168.123.161")
AES_KEY = (os.environ.get("GO2_AES_KEY") or "").strip() or None
JPEG_QUALITY = int(os.environ.get("GO2_JPEG_QUALITY", "80"))
JPEG_PARAMS = [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]

# Sport api ids (official unitree_sdk2 header; verified on 1.1.15 by Azimuth)
API = {"BalanceStand": 1002, "StopMove": 1003, "StandUp": 1004, "StandDown": 1005,
       "RecoveryStand": 1006, "Move": 1008, "Sit": 1009, "RiseSit": 1010, "Hello": 1016}
MOTION_SWITCHER = {"CheckMode": 1001, "SelectMode": 1002}

# Commands the dashboard sends. "stand" is RecoveryStand, the balance stance:
# a plain StandUp (1004) locks the joints and the robot then refuses Move.
LENIENT_CODES = {"sit": {-1}, "shake": {-1}}     # vendor -1 observed as benign for these
CMD_MIN_GAP_S = 2.0
REQUEST_TIMEOUT_S = 5.0
TELEMETRY_STALE_S = 1.5
LYING_BODY_HEIGHT_M = 0.15

app = Flask(__name__)


@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


# ── DDS link ────────────────────────────────────────────────────────────────

class DDSLink:
    """rclpy node in its own context + executor thread; request/response by id."""

    def __init__(self):
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
        from unitree_api.msg import Request, Response
        from unitree_go.msg import LowState, SportModeState
        self.Request = Request
        qos_state = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST,
                               depth=1, durability=DurabilityPolicy.VOLATILE)
        qos_resp = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST,
                              depth=32, durability=DurabilityPolicy.VOLATILE)
        qos_req = QoSProfile(reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST,
                             depth=8, durability=DurabilityPolicy.VOLATILE)
        self.ctx = rclpy.Context()
        rclpy.init(args=None, context=self.ctx)
        self.node = rclpy.create_node("watchdog_go2_service", context=self.ctx)
        self.lock = threading.Lock()
        self.pending = {}                       # rid -> [Event, code, data]
        self.rid = int(time.time() * 1000) % 1000000000
        self.battery = {"soc": None, "voltage": None, "current": None}
        self.body_height = None
        self.last_state = 0.0
        self.pubs = {}
        for svc in ("sport", "motion_switcher"):
            self.pubs[svc] = self.node.create_publisher(Request, "/api/%s/request" % svc, qos_req)
            self.node.create_subscription(Response, "/api/%s/response" % svc, self._on_resp, qos_resp)
        self.node.create_subscription(LowState, "/lf/lowstate", self._on_low, qos_state)
        self.node.create_subscription(SportModeState, "/lf/sportmodestate", self._on_sport, qos_state)
        self.exec = SingleThreadedExecutor(context=self.ctx)
        self.exec.add_node(self.node)
        threading.Thread(target=self.exec.spin, name="dds-executor", daemon=True).start()

    def _on_low(self, m):
        b = m.bms_state
        self.battery = {"soc": int(b.soc), "voltage": float(m.power_v), "current": int(b.current)}

    def _on_sport(self, m):
        self.body_height = float(m.body_height)
        self.last_state = time.monotonic()

    def _on_resp(self, m):
        rid = int(m.header.identity.id)
        with self.lock:
            slot = self.pending.get(rid)
        if slot is not None:
            slot[1] = int(m.header.status.code)
            slot[2] = m.data
            slot[0].set()

    def alive(self):
        return self.last_state and time.monotonic() - self.last_state < TELEMETRY_STALE_S

    def request(self, api_id, parameter=None, svc="sport", timeout=REQUEST_TIMEOUT_S):
        """(code, data). code None = no reply within timeout."""
        with self.lock:
            self.rid = (self.rid + 1) % 2000000000
            rid = self.rid
            slot = [threading.Event(), None, None]
            self.pending[rid] = slot
        r = self.Request()
        r.header.identity.id = rid
        r.header.identity.api_id = int(api_id)
        r.header.lease.id = 0
        r.header.policy.priority = 0
        r.header.policy.noreply = False
        r.parameter = json.dumps(parameter) if isinstance(parameter, (dict, list)) else (parameter or "")
        self.pubs[svc].publish(r)
        try:
            if not slot[0].wait(timeout):
                return None, None
            return slot[1], slot[2]
        finally:
            with self.lock:
                self.pending.pop(rid, None)


dds = None
dds_error = None


def start_dds():
    global dds, dds_error
    while dds is None:
        try:
            dds = DDSLink()
            print("[DDS] link up (sport + motion_switcher, /lf telemetry)", flush=True)
        except Exception as e:                           # noqa: BLE001
            dds_error = str(e)
            print("[DDS] init failed: %s — retrying in 5s" % e, flush=True)
            time.sleep(5)


# ── Video over WebRTC (video only) ──────────────────────────────────────────

frame_lock = threading.Lock()
latest_jpeg = None
frame_counter = 0
video_connected = False
encode_queue = queue.Queue(maxsize=2)


def encoder():
    global latest_jpeg, frame_counter
    while True:
        img = encode_queue.get()
        ok, buf = cv2.imencode(".jpg", img, JPEG_PARAMS)
        if ok:
            with frame_lock:
                latest_jpeg = buf.tobytes()
                frame_counter += 1


async def on_track(track):
    while True:
        frame = await track.recv()
        img = frame.to_ndarray(format="bgr24")
        try:
            encode_queue.put_nowait(img)
        except queue.Full:
            pass                                          # encoder behind: drop, keep latency low


async def video_loop():
    global video_connected
    from unitree_webrtc_connect.webrtc_driver import UnitreeWebRTCConnection, WebRTCConnectionMethod
    attempt = 0
    while True:
        attempt += 1
        conn = None
        try:
            kw = {"ip": ROBOT_IP}
            if AES_KEY:
                kw["aes_128_key"] = AES_KEY
            conn = UnitreeWebRTCConnection(WebRTCConnectionMethod.LocalSTA, **kw)
            await conn.connect()
            conn.video.switchVideoChannel(True)
            conn.video.add_track_callback(on_track)
            video_connected = True
            attempt = 0
            print("[Video] WebRTC video link up (%s)" % ("AES key" if AES_KEY else "no key"), flush=True)
            while True:                                   # stay up; the library reconnects nothing
                await asyncio.sleep(2)
                if getattr(conn, "isConnected", True) is False:
                    raise RuntimeError("WebRTC link dropped")
        except Exception as e:                            # noqa: BLE001
            video_connected = False
            wait = min(5 * max(attempt, 1), 30)
            print("[Video] %s — retry in %ss" % (e, wait), flush=True)
            try:
                if conn is not None:
                    await conn.disconnect()
            except Exception:                             # noqa: BLE001
                pass
            await asyncio.sleep(wait)


def start_video():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(video_loop())


# ── Command safety ───────────────────────────────────────────────────────────

cmd_lock = threading.Lock()
busy = False
last_cmd_ts = 0.0
posture = "unknown"          # lying | standing | sitting | unknown (from commands + body height)


def current_posture():
    if dds and dds.body_height is not None and dds.body_height < LYING_BODY_HEIGHT_M:
        return "lying"
    return posture


def link_ok():
    return dds is not None and dds.alive()


def result(code, name):
    if code is None:
        return False, "No reply from robot within %.0fs" % REQUEST_TIMEOUT_S
    ok = code == 0 or code in LENIENT_CODES.get(name, set())
    return ok, ("ok" if code == 0 else "robot code %s%s" % (code, " (tolerated)" if ok else ""))


def run_command(name):
    """Map a dashboard command to the right sport request for the current posture."""
    global posture
    p = current_posture()
    if name == "stand":
        api = API["RiseSit"] if p == "sitting" else API["RecoveryStand"]
    elif name == "crouch":
        api = API["StandDown"]
    elif name == "sit":
        if p == "lying":
            return 409, {"success": False, "message": "Stand up before sitting."}
        api = API["Sit"]
    elif name == "shake":
        if p in ("lying", "sitting"):
            return 409, {"success": False, "message": "Stand up first — the dog shakes hands from standing."}
        api = API["Hello"]
    else:
        return 400, {"success": False, "message": "Invalid command"}
    code, _ = dds.request(api)
    ok, msg = result(code, name)
    if ok:
        posture = {"stand": "standing", "crouch": "lying", "sit": "sitting"}.get(name, posture)
    print("[Command] %s (api %s) -> code %s" % (name, api, code), flush=True)
    return 200, {"success": ok, "message": msg, "raw_status": {"code": code}}


# ── HTTP ─────────────────────────────────────────────────────────────────────

@app.route("/status")
def status():
    with frame_lock:
        has_video = latest_jpeg is not None and video_connected
    return jsonify({
        "connected": bool(link_ok()),
        "battery_soc": dds.battery["soc"] if dds else None,
        "has_video": has_video,
        "transport": "dds",
        "video_transport": "webrtc",
        "posture": current_posture(),
        "body_height": round(dds.body_height, 3) if dds and dds.body_height is not None else None,
    })


@app.route("/battery")
def battery():
    b = dict(dds.battery) if dds else {"soc": None, "voltage": None, "current": None}
    b["connected"] = bool(link_ok())
    return jsonify(b)


@app.route("/video_feed")
def video_feed():
    def generate():
        seen = -1
        while True:
            with frame_lock:
                jpeg, n = latest_jpeg, frame_counter
            if jpeg is not None and n != seen:
                seen = n
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            else:
                time.sleep(0.01)
    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/command", methods=["POST"])
def handle_command():
    global busy, last_cmd_ts
    name = (request.get_json(silent=True) or {}).get("command")
    if not link_ok():
        return jsonify({"success": False, "message": "Robot not connected (no DDS telemetry)"}), 503
    with cmd_lock:
        if busy:
            return jsonify({"success": False, "message": "Robot busy — wait for current command to finish"}), 429
        gap = time.time() - last_cmd_ts
        if gap < CMD_MIN_GAP_S:
            return jsonify({"success": False, "message": "Command cooldown — wait %.1fs" % (CMD_MIN_GAP_S - gap)}), 429
        busy = True
    try:
        http, body = run_command(name)
        return jsonify(body), http
    finally:
        with cmd_lock:
            busy = False
            last_cmd_ts = time.time()


@app.route("/move", methods=["POST"])
def handle_move():
    if not link_ok():
        return jsonify({"success": False, "message": "Robot not connected (no DDS telemetry)"}), 503
    if current_posture() in ("lying", "sitting"):
        return jsonify({"success": False, "message": "Stand up before moving."}), 409
    d = request.get_json(silent=True) or {}
    try:
        vx, vy, vyaw = float(d.get("vx", 0)), float(d.get("vy", 0)), float(d.get("vyaw", 0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "vx/vy/vyaw must be numbers"}), 400
    # Same envelope as Azimuth's nudge limits.
    vx = max(-0.15, min(0.25, vx)); vy = max(-0.2, min(0.2, vy)); vyaw = max(-0.5, min(0.5, vyaw))
    code, _ = dds.request(API["Move"], {"x": vx, "y": vy, "z": vyaw}, timeout=2.0)
    return jsonify({"success": code == 0, "code": code})


@app.route("/stop", methods=["POST"])
def handle_stop():
    # Always sent (no posture/busy gate): stopping must never be refused.
    if dds is None:
        return jsonify({"success": False, "message": "DDS link not up"}), 503
    code, _ = dds.request(API["StopMove"], timeout=2.0)
    return jsonify({"success": code == 0, "code": code, "message": "Stop sent"})


@app.route("/motion_mode", methods=["POST"])
def motion_mode():
    mode = (request.get_json(silent=True) or {}).get("mode", "normal")
    if not isinstance(mode, str):
        return jsonify({"success": False, "message": "Mode must be a string"}), 400
    if not link_ok():
        return jsonify({"success": False, "message": "Robot not connected"}), 503
    code, data = dds.request(MOTION_SWITCHER["SelectMode"], {"name": mode}, svc="motion_switcher")
    return jsonify({"success": code == 0, "code": code, "message": data or ""})


if __name__ == "__main__":
    threading.Thread(target=start_dds, name="dds-init", daemon=True).start()
    threading.Thread(target=encoder, name="jpeg-encoder", daemon=True).start()
    threading.Thread(target=start_video, name="video", daemon=True).start()
    app.run(host="0.0.0.0", port=5001, threaded=True)
