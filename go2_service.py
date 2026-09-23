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
    and Azimuth never run at the same time (the units Conflicts= each other),
    so nobody else holds the sport lease.
  * Video only over WebRTC (library 2.2.0, per-device AES key from
    GO2_AES_KEY): the front camera has no usable DDS framing yet.

Safety model (this box sits next to the robot, so it owns the deadman):
  * Every Move buys a short motion lease (MOVE_LEASE_S). A supervisor sends
    StopMove when the lease lapses — a dead dashboard, Thor or network can
    never leave the dog walking — and keeps retrying until the robot
    confirms the stop. Until then all movement is refused.
  * Move and Stop publish under one actuation lock with a drive generation:
    a Stop bumps the generation, so a Move admitted before it can never be
    published after it.
  * Posture comes from fresh telemetry (body height), not from the last
    command, so a remote-controller change is seen. Movement and gestures
    are only admitted when the dog is verifiably standing, no posture
    command is in flight, and the settle time after one has passed.

Same HTTP contract as the old WebRTC service on :5001:
  GET /status /battery /video_feed   POST /command /move /stop /motion_mode
"""
import asyncio
import json
import math
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
API = {"StopMove": 1003, "StandDown": 1005, "RecoveryStand": 1006, "Move": 1008,
       "Sit": 1009, "RiseSit": 1010, "Hello": 1016}
MOTION_SWITCHER = {"CheckMode": 1001, "SelectMode": 1002}

LENIENT_CODES = {"sit": {-1}, "shake": {-1}}      # vendor -1 observed as benign for these
CMD_MIN_GAP_S = 2.0
REQUEST_TIMEOUT_S = 5.0
MOVE_REPLY_TIMEOUT_S = 1.0
STOP_REPLY_TIMEOUT_S = 1.0
MOVE_LEASE_S = 0.4            # Azimuth's teleop lease: a Move authorizes this long, then the deadman stops it
STOP_RETRY_S = 0.5
POSTURE_SETTLE_S = 2.0        # after a posture command, telemetry must settle before moving
TELEMETRY_STALE_S = 1.5
STANDING_MIN_M = 0.27         # measured on Scout (1.1.15): standing 0.31-0.33, sit 0.22, lying 0.08
LYING_MAX_M = 0.15
VIDEO_STALE_S = 2.0
VIDEO_RECONNECT_S = 10.0
LIMITS = {"vx": (-0.15, 0.25), "vy": (-0.2, 0.2), "vyaw": (-0.5, 0.5)}   # Azimuth's envelope
# Measured by Azimuth on this robot (edge/commands.py): below 0.22 m/s forward the
# gait stalls after ~1.8 s while still ACKing every Move; below 0.45 rad/s it does
# not turn. Non-zero commands are snapped up to these floors, like Azimuth's teleop.
MIN_VX_FWD = 0.22
MIN_VYAW = 0.45
DEADBAND = 0.05
# Rest verification (Azimuth's settle_still): a stop counts only when distinct fresh
# sport samples after it show the body still, continuously for STILL_HOLD_S.
STILL_V = 0.03                # m/s planar speed that counts as stopped
STILL_W = 0.05                # rad/s yaw rate that counts as stopped
STILL_HOLD_S = 0.3
STILL_MIN_SAMPLES = 4
STILL_DEADLINE_S = 2.5

app = Flask(__name__)


@app.after_request
def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


def log(msg):
    print(msg, flush=True)


# ── DDS link ────────────────────────────────────────────────────────────────

class DDSLink:
    """rclpy node in its own context + executor thread; request/response by id."""

    def __init__(self):
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
        from unitree_api.msg import Request, Response
        from unitree_go.msg import LowState, SportModeState
        self._rclpy = rclpy
        self.Request = Request
        self.dead = False
        self.lock = threading.Lock()
        self.pending = {}                       # rid -> [Event, code, data]
        self.rid = int(time.time() * 1000) % 1000000000
        self.battery = {"soc": None, "voltage": None, "current": None}
        self.body_height = None
        self.motion = None                    # (planar speed, |yaw rate|) or None if not finite
        self.last_state = 0.0
        self.ctx = rclpy.Context()
        rclpy.init(args=None, context=self.ctx)
        try:
            qos_state = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST,
                                   depth=1, durability=DurabilityPolicy.VOLATILE)
            qos_resp = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST,
                                  depth=32, durability=DurabilityPolicy.VOLATILE)
            qos_req = QoSProfile(reliability=ReliabilityPolicy.RELIABLE, history=HistoryPolicy.KEEP_LAST,
                                 depth=8, durability=DurabilityPolicy.VOLATILE)
            self.node = rclpy.create_node("watchdog_go2_service", context=self.ctx)
            self.pubs = {}
            for svc in ("sport", "motion_switcher"):
                self.pubs[svc] = self.node.create_publisher(Request, "/api/%s/request" % svc, qos_req)
                self.node.create_subscription(Response, "/api/%s/response" % svc, self._on_resp, qos_resp)
            self.node.create_subscription(LowState, "/lf/lowstate", self._on_low, qos_state)
            self.node.create_subscription(SportModeState, "/lf/sportmodestate", self._on_sport, qos_state)
            self.exec = SingleThreadedExecutor(context=self.ctx)
            self.exec.add_node(self.node)
        except Exception:
            self.close()
            raise
        threading.Thread(target=self._spin, name="dds-executor", daemon=True).start()

    def _spin(self):
        try:
            self.exec.spin()
        except Exception as e:                           # noqa: BLE001
            log("[DDS] executor died: %s" % e)
        finally:
            self.dead = True

    def close(self):
        try:
            if getattr(self, "node", None) is not None:
                self.node.destroy_node()
        except Exception:                                # noqa: BLE001
            pass
        try:
            if self.ctx.ok():
                self._rclpy.shutdown(context=self.ctx)
        except Exception:                                # noqa: BLE001
            pass

    def _on_low(self, m):
        b = m.bms_state
        self.battery = {"soc": int(b.soc), "voltage": float(m.power_v), "current": int(b.current)}

    def _on_sport(self, m):
        self.body_height = float(m.body_height)
        try:
            v = math.hypot(float(m.velocity[0]), float(m.velocity[1]))
            w = abs(float(m.yaw_speed))
            self.motion = (v, w) if math.isfinite(v) and math.isfinite(w) else None
        except (AttributeError, IndexError, TypeError, ValueError):
            self.motion = None
        self.last_state = time.monotonic()

    def _on_resp(self, m):
        rid = int(m.header.identity.id)
        with self.lock:
            slot = self.pending.get(rid)
        if slot is not None:                             # late/foreign replies are ignored
            slot[1] = int(m.header.status.code)
            slot[2] = m.data
            slot[0].set()

    def alive(self):
        return (not self.dead) and self.last_state and time.monotonic() - self.last_state < TELEMETRY_STALE_S

    def send(self, api_id, parameter=None, svc="sport"):
        """Publish a request; returns (rid, slot). Never blocks on the robot."""
        with self.lock:
            self.rid = (self.rid + 1) % 2000000000
            rid = self.rid
            slot = [threading.Event(), None, None]
            self.pending[rid] = slot
        try:
            r = self.Request()
            r.header.identity.id = rid
            r.header.identity.api_id = int(api_id)
            r.header.lease.id = 0
            r.header.policy.priority = 0
            r.header.policy.noreply = False
            r.parameter = json.dumps(parameter) if isinstance(parameter, (dict, list)) else (parameter or "")
            self.pubs[svc].publish(r)
        except Exception:
            with self.lock:
                self.pending.pop(rid, None)
            raise
        return rid, slot

    def wait(self, rid, slot, timeout):
        """(code, data); code None = no reply within timeout."""
        try:
            if not slot[0].wait(timeout):
                return None, None
            return slot[1], slot[2]
        finally:
            with self.lock:
                self.pending.pop(rid, None)

    def request(self, api_id, parameter=None, svc="sport", timeout=REQUEST_TIMEOUT_S):
        rid, slot = self.send(api_id, parameter, svc)
        return self.wait(rid, slot, timeout)


dds = None
dds_lock = threading.Lock()


def dds_supervisor():
    """Create the link, and re-create it if its executor ever dies."""
    global dds
    while True:
        with dds_lock:
            current = dds
        if current is not None and current.dead:
            log("[DDS] link dead — rebuilding")
            with dds_lock:
                dds = None
            current.close()
            current = None
        if current is None:
            try:
                link = DDSLink()
                with dds_lock:
                    dds = link
                log("[DDS] link up (sport + motion_switcher, /lf telemetry)")
            except Exception as e:                       # noqa: BLE001
                log("[DDS] init failed: %s — retrying in 5s" % e)
                time.sleep(5)
                continue
        time.sleep(1)


def link():
    with dds_lock:
        return dds


def link_ok():
    d = link()
    return d is not None and bool(d.alive())


def telemetry_posture():
    """lying | low (sitting or in transition) | standing | unknown — fresh telemetry only."""
    d = link()
    if d is None or not d.alive() or d.body_height is None:
        return "unknown"
    h = d.body_height
    if h < LYING_MAX_M:
        return "lying"
    if h < STANDING_MIN_M:
        return "low"
    return "standing"


# ── Actuation: one lock, drive generations, Orin-side deadman ───────────────

def settle_still(t_stop):
    """True once distinct fresh samples after t_stop show the body still for
    STILL_HOLD_S (>= STILL_MIN_SAMPLES), within STILL_DEADLINE_S."""
    held_since = None; samples = 0; last_seen = None
    while time.monotonic() - t_stop < STILL_DEADLINE_S:
        d = link()
        at = d.last_state if d else 0
        if d and at and at > t_stop and at != last_seen and time.monotonic() - at < 0.5:
            last_seen = at
            m = d.motion
            if m is not None and m[0] < STILL_V and m[1] < STILL_W:
                held_since = held_since or time.monotonic(); samples += 1
                if time.monotonic() - held_since >= STILL_HOLD_S and samples >= STILL_MIN_SAMPLES:
                    return True
            else:
                held_since = None; samples = 0
        time.sleep(0.02)
    return False


def snap(v, lo, hi, floor):
    if not math.isfinite(v) or abs(v) < DEADBAND:
        return 0.0
    v = max(lo, min(hi, v))
    if floor and 0 < abs(v) < floor:
        v = floor if v > 0 else (lo if lo > -floor else -floor)
    return v


class Actuator:
    def __init__(self):
        self.lock = threading.Lock()
        self.gen = 0                 # bumped by every stop; a Move publishes only in its own gen
        self.moving = False          # a Move was published and no stop has been confirmed since
        self.lease_until = 0.0       # monotonic: the deadman stops the dog after this
        self.stop_confirmed = True   # False while a stop is outstanding: all motion refused
        self.last_stop_attempt = 0.0
        self.posture_busy = False
        self.settle_until = 0.0
        self.last_cmd_ts = 0.0
        self.last_move_seq = 0       # client seqs: a Move older than the newest stop/move never drives
        self.stop_seq = 0

    # -- stop -------------------------------------------------------------
    def stop(self, reason, seq=None):
        d = link()
        if seq is not None:
            with self.lock:
                self.stop_seq = max(self.stop_seq, int(seq))
        if d is None:
            with self.lock:
                self.stop_confirmed = False
            return None
        with self.lock:
            self.gen += 1
            self.lease_until = 0.0
            self.stop_confirmed = False
            self.last_stop_attempt = time.monotonic()
            try:
                rid, slot = d.send(API["StopMove"])
            except Exception as e:                       # noqa: BLE001
                log("[Stop] publish failed (%s): %s" % (reason, e))
                return None
            my_gen = self.gen
        t_stop = time.monotonic()
        code, _ = d.wait(rid, slot, STOP_REPLY_TIMEOUT_S)
        still = code == 0 and settle_still(t_stop)       # an ACK alone is not a stop
        if still:
            with self.lock:
                if self.gen == my_gen:                    # no newer stop/move since
                    self.stop_confirmed = True
                    self.moving = False
        log("[Stop] %s -> code %s, %s" % (reason, code, "verified at rest" if still else "NOT verified — will retry"))
        return 0 if still else (code if code else -1)

    def supervise(self):
        """Deadman + stop retry, 20 Hz."""
        while True:
            time.sleep(0.05)
            now = time.monotonic()
            with self.lock:
                lapse = self.moving and self.stop_confirmed and self.lease_until and now > self.lease_until
                retry = (not self.stop_confirmed) and now - self.last_stop_attempt > STOP_RETRY_S
            if lapse:
                self.stop("deadman: no move within %.1fs" % MOVE_LEASE_S)
            elif retry:
                self.stop("retrying unconfirmed stop")

    # -- move -------------------------------------------------------------
    def move(self, vx, vy, vyaw, seq=None):
        d = link()
        if d is None or not d.alive():
            return 503, {"success": False, "message": "Robot not connected (no DDS telemetry)"}
        with self.lock:
            if seq is not None:
                seq = int(seq)
                if seq <= self.stop_seq or seq <= self.last_move_seq:
                    return 409, {"success": False, "message": "Superseded — a newer stop or move exists."}
                self.last_move_seq = seq
            if not self.stop_confirmed:
                return 409, {"success": False, "message": "Stopping — movement is blocked until the robot confirms the stop."}
            if self.posture_busy or time.monotonic() < self.settle_until:
                return 409, {"success": False, "message": "Posture change in progress — wait a moment."}
            p = telemetry_posture()
            if p != "standing":
                return 409, {"success": False, "message": "Stand up before moving (robot reads %s)." % p}
            self.moving = True
            self.lease_until = time.monotonic() + MOVE_LEASE_S
            try:
                rid, slot = d.send(API["Move"], {"x": vx, "y": vy, "z": vyaw})
            except Exception as e:                       # noqa: BLE001
                return 503, {"success": False, "message": "Move publish failed: %s" % e}
        code, _ = d.wait(rid, slot, MOVE_REPLY_TIMEOUT_S)
        return 200, {"success": code == 0, "code": code}

    # -- posture / gestures ------------------------------------------------
    def _ensure_stopped(self):
        with self.lock:
            clean = self.stop_confirmed and not self.moving
        if clean:
            return True
        return self.stop("before posture command") == 0

    def command(self, name):
        d = link()
        if d is None or not d.alive():
            return 503, {"success": False, "message": "Robot not connected (no DDS telemetry)"}
        with self.lock:
            if self.posture_busy:
                return 429, {"success": False, "message": "Robot busy — wait for current command to finish"}
            gap = time.time() - self.last_cmd_ts
            if gap < CMD_MIN_GAP_S:
                return 429, {"success": False, "message": "Command cooldown — wait %.1fs" % (CMD_MIN_GAP_S - gap)}
            self.posture_busy = True
        try:
            if not self._ensure_stopped():
                return 409, {"success": False, "message": "Could not confirm the robot stopped — command not sent."}
            p = telemetry_posture()
            if name == "stand":
                api = API["RiseSit"] if p == "low" else API["RecoveryStand"]
            elif name == "crouch":
                api = API["StandDown"]
            elif name == "sit":
                if p != "standing":
                    return 409, {"success": False, "message": "Stand up before sitting (robot reads %s)." % p}
                api = API["Sit"]
            elif name == "shake":
                if p != "standing":
                    return 409, {"success": False, "message": "Stand up first — the dog shakes hands from standing (robot reads %s)." % p}
                api = API["Hello"]
            else:
                return 400, {"success": False, "message": "Invalid command"}
            code, _ = d.request(api)
            ok = code == 0 or code in LENIENT_CODES.get(name, set())
            msg = ("No reply from robot within %.0fs" % REQUEST_TIMEOUT_S if code is None
                   else "ok" if code == 0 else "robot code %s%s" % (code, " (tolerated)" if ok else ""))
            log("[Command] %s (api %s, robot read %s) -> code %s" % (name, api, p, code))
            return 200, {"success": ok, "message": msg, "raw_status": {"code": code}}
        finally:
            with self.lock:
                self.posture_busy = False
                self.last_cmd_ts = time.time()
                self.settle_until = time.monotonic() + POSTURE_SETTLE_S

    def motion_mode(self, mode):
        d = link()
        if d is None or not d.alive():
            return 503, {"success": False, "message": "Robot not connected"}
        with self.lock:
            if self.posture_busy:
                return 429, {"success": False, "message": "Robot busy"}
            self.posture_busy = True
        try:
            code, data = d.request(MOTION_SWITCHER["CheckMode"], svc="motion_switcher")
            current = None
            try:
                current = (json.loads(data) if data else {}).get("name")
            except (ValueError, AttributeError):
                pass
            if code == 0 and current == mode:
                return 200, {"success": True, "message": "already in '%s'" % mode, "code": 0}
            if not self._ensure_stopped():
                return 409, {"success": False, "message": "Could not confirm the robot stopped — mode not changed."}
            code, data = d.request(MOTION_SWITCHER["SelectMode"], {"name": mode}, svc="motion_switcher")
            log("[MotionMode] %s -> %s (code %s)" % (current, mode, code))
            return 200, {"success": code == 0, "code": code, "message": data or ""}
        finally:
            with self.lock:
                self.posture_busy = False
                self.settle_until = time.monotonic() + POSTURE_SETTLE_S


act = Actuator()


# ── Video over WebRTC (video only) ──────────────────────────────────────────

frame_lock = threading.Lock()
latest_jpeg = None
frame_counter = 0
last_frame_mono = 0.0
video_connected = False
encode_queue = queue.Queue(maxsize=2)


def encoder():
    global latest_jpeg, frame_counter, last_frame_mono
    while True:
        img = encode_queue.get()
        try:
            ok, buf = cv2.imencode(".jpg", img, JPEG_PARAMS)
        except Exception as e:                           # noqa: BLE001
            log("[Video] encode error: %s" % e)
            continue
        if ok:
            with frame_lock:
                latest_jpeg = buf.tobytes()
                frame_counter += 1
                last_frame_mono = time.monotonic()


async def on_track(track):
    while True:
        frame = await track.recv()
        try:
            img = frame.to_ndarray(format="bgr24")
        except Exception as e:                           # noqa: BLE001
            log("[Video] frame conversion error: %s" % e)
            continue
        try:
            encode_queue.put_nowait(img)
        except queue.Full:
            pass                                          # encoder behind: drop, keep latency low


def video_fresh():
    with frame_lock:
        return latest_jpeg is not None and time.monotonic() - last_frame_mono < VIDEO_STALE_S


async def video_loop():
    global video_connected, latest_jpeg
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
            up_since = time.monotonic()
            log("[Video] WebRTC video link up (%s)" % ("AES key" if AES_KEY else "no key"))
            while True:
                await asyncio.sleep(2)
                if conn.isConnected is False:
                    raise RuntimeError("WebRTC link dropped")
                with frame_lock:
                    last = last_frame_mono
                if time.monotonic() - max(last, up_since) > VIDEO_RECONNECT_S:
                    raise RuntimeError("no video frames for %.0fs" % VIDEO_RECONNECT_S)
                attempt = 0
        except Exception as e:                            # noqa: BLE001
            video_connected = False
            with frame_lock:
                latest_jpeg = None                        # never serve a frozen picture
            wait = min(5 * max(attempt, 1), 30)
            log("[Video] %s — retry in %ss" % (e, wait))
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


# ── HTTP ─────────────────────────────────────────────────────────────────────

@app.route("/status")
def status():
    d = link()
    with act.lock:
        stop_ok = act.stop_confirmed
    return jsonify({
        "connected": link_ok(),
        "battery_soc": d.battery["soc"] if d else None,
        "has_video": video_connected and video_fresh(),
        "transport": "dds",
        "video_transport": "webrtc",
        "posture": telemetry_posture(),
        "body_height": round(d.body_height, 3) if d and d.body_height is not None else None,
        "stop_confirmed": stop_ok,
    })


@app.route("/battery")
def battery():
    d = link()
    b = dict(d.battery) if d else {"soc": None, "voltage": None, "current": None}
    b["connected"] = link_ok()
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
    name = (request.get_json(silent=True) or {}).get("command")
    http, body = act.command(name)
    return jsonify(body), http


@app.route("/move", methods=["POST"])
def handle_move():
    d = request.get_json(silent=True) or {}
    vals = {}
    for k in ("vx", "vy", "vyaw"):
        try:
            v = float(d.get(k, 0))
        except (TypeError, ValueError):
            return jsonify({"success": False, "message": "%s must be a number" % k}), 400
        if not math.isfinite(v):
            return jsonify({"success": False, "message": "%s must be finite" % k}), 400
        lo, hi = LIMITS[k]
        floor = MIN_VX_FWD if k == "vx" else MIN_VYAW if k == "vyaw" else 0
        vals[k] = snap(v, lo, hi, floor)
    seq = d.get("seq")
    if seq is not None and (not isinstance(seq, int) or isinstance(seq, bool)):
        return jsonify({"success": False, "message": "seq must be an integer"}), 400
    http, body = act.move(vals["vx"], vals["vy"], vals["vyaw"], seq)
    body.setdefault("applied", vals)
    return jsonify(body), http


@app.route("/stop", methods=["POST"])
def handle_stop():
    # Never refused: no posture/busy gate. Unconfirmed stops keep being retried.
    seq = (request.get_json(silent=True) or {}).get("seq")
    code = act.stop("operator stop", seq if isinstance(seq, int) and not isinstance(seq, bool) else None)
    if code is None and link() is None:
        return jsonify({"success": False, "message": "DDS link not up — stop will be retried"}), 503
    return jsonify({"success": code == 0, "code": code,
                    "message": "Stop confirmed" if code == 0 else "Stop sent — retrying until confirmed"})


@app.route("/motion_mode", methods=["POST"])
def motion_mode():
    mode = (request.get_json(silent=True) or {}).get("mode", "normal")
    if not isinstance(mode, str) or not mode:
        return jsonify({"success": False, "message": "Mode must be a non-empty string"}), 400
    http, body = act.motion_mode(mode)
    return jsonify(body), http


if __name__ == "__main__":
    threading.Thread(target=dds_supervisor, name="dds-supervisor", daemon=True).start()
    threading.Thread(target=act.supervise, name="deadman", daemon=True).start()
    threading.Thread(target=encoder, name="jpeg-encoder", daemon=True).start()
    threading.Thread(target=start_video, name="video", daemon=True).start()
    app.run(host="0.0.0.0", port=5001, threaded=True)
