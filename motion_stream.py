"""Live joint mirror + maneuver recognition (ADR 0010).

Reads the robot link's /joints stream (20 Hz: 12 joint angles, attitude, body
height), relays it to the cloud real-time channel in small batches so booth
dashboards can mirror the dog's motion, and recognizes maneuvers (hello/shake,
sit, stand up, lie down) from the motion itself: the dog does not report which
remote/app trick is running. Recognized maneuvers also go out as telemetry
`maneuver` events, so the agent and history see them.

Cloud channels (one per show cloud, chosen live by the conference demo profile):
Azure Web PubSub (hub/group `motion`, send-to-group-only token) and AWS AppSync
Events (namespace `motion`, publish-only IAM key). A dropped channel just drops
frames, since a live twin has no use for old ones."""
import json
import logging
import os
import threading
import time
from collections import deque
from typing import Callable, List, Optional

logger = logging.getLogger("motion_stream")

BATCH_S = 0.2                      # publish 5 batches/s
STANDING_MIN_M = 0.27              # same posture thresholds as the robot link (go2_service.py)
LYING_MAX_M = 0.15
HELLO_THIGH_MAX = -0.30            # front thigh swung forward past this (rad) = paw raised; standing ~0.8
HELLO_HOLD_S = 0.3
POSTURE_HOLD_S = 1.0               # a posture must hold this long before a transition counts
REPEAT_GAP_S = 3.0                 # the same maneuver is not reported again within this gap
GAP_RESET_S = 1.0                  # a gap in frames longer than this resets pending holds
MANEUVER_MAX_AGE_S = 10.0          # older maneuvers are dropped, never published as current
FR_THIGH, FL_THIGH = 1, 4          # joint order FR, FL, RR, RL x hip/thigh/calf (confirmed 2026-10-30)


def posture_of(h: Optional[float]) -> str:
    if h is None:
        return "unknown"
    return "lying" if h < LYING_MAX_M else "low" if h < STANDING_MIN_M else "standing"


class ManeuverRecognizer:
    """Feed frames in time order; returns a maneuver dict when one completes."""

    def __init__(self):
        self.posture = "unknown"
        self._cand, self._cand_since = None, 0.0
        self._paw_since = {FR_THIGH: None, FL_THIGH: None}
        self._paw_fired = {FR_THIGH: False, FL_THIGH: False}   # latched until that paw comes down
        self._last = {}
        self._prev_t = None

    def _fire(self, name: str, t: float, **detail) -> Optional[dict]:
        if t - self._last.get(name, -1e9) < REPEAT_GAP_S:
            return None
        self._last[name] = t
        return dict(name=name, t=t, **detail)

    def feed(self, f: dict) -> Optional[dict]:
        t, q, h = f["t"], f["q"], f.get("h")
        out = None
        # A gap in the stream or missing body height (sport state stale): drop pending
        # holds, so nothing fires from stitched-together or half-known frames.
        gap = self._prev_t is not None and t - self._prev_t > GAP_RESET_S
        self._prev_t = t
        if gap or h is None:
            # Unobserved interval: forget holds AND the posture baseline. The next
            # posture is re-established without reporting a transition across the gap.
            self._paw_since = {k: None for k in self._paw_since}
            self._cand, self.posture = None, "unknown"
            if h is None:
                return None
        # Hello / shake: one front thigh swung well forward, held briefly, while upright.
        # One event per raise: it re-arms only after that paw comes back down.
        for idx, side in ((FR_THIGH, "front right"), (FL_THIGH, "front left")):
            upright = self.posture in ("standing", "low") and posture_of(h) in ("standing", "low")
            if q[idx] < HELLO_THIGH_MAX and upright:
                self._paw_since[idx] = self._paw_since[idx] or t
                if not self._paw_fired[idx] and t - self._paw_since[idx] >= HELLO_HOLD_S:
                    m = self._fire("hello", t, paw=side)
                    if m:
                        self._paw_fired[idx] = True
                        out = out or m
            elif q[idx] >= HELLO_THIGH_MAX:
                self._paw_since[idx] = None
                self._paw_fired[idx] = False         # paw down: re-arm
            else:
                self._paw_since[idx] = None          # raised but not upright: the hold restarts; a fired latch stays
        # Posture transitions from body height, debounced.
        p = posture_of(h)
        if p != self._cand:
            self._cand, self._cand_since = p, t
        elif p != self.posture and p != "unknown" and t - self._cand_since >= POSTURE_HOLD_S:
            prev, self.posture = self.posture, p
            name = {("lying", "standing"): "stand_up", ("low", "standing"): "stand_up",
                    ("standing", "lying"): "lie_down", ("low", "lying"): "lie_down",
                    ("standing", "low"): "sit"}.get((prev, p))
            if name:
                out = out or self._fire(name, t, posture_from=prev, posture_to=p)
        return out


class _Channel:
    """One cloud's live-twin publisher with its own queue, so a slow or absent
    cloud never delays another. Subclasses implement connect() and send()."""
    cloud = ""

    def __init__(self, device_id: str):
        self.device_id = device_id
        self.frames: deque = deque(maxlen=200)
        self.maneuvers: deque = deque(maxlen=20)
        self.lock = threading.Lock()
        self.stats = {"batches_out": 0, "publisher": "down"}

    def offer(self, frame: dict, maneuver: Optional[dict]):
        with self.lock:
            self.frames.append(frame)
            if maneuver:
                self.maneuvers.append(dict(maneuver, _rx=time.monotonic()))

    def _take(self):
        with self.lock:
            frames, self.frames = list(self.frames), deque(maxlen=200)
            now = time.monotonic()
            mans = [{k: v for k, v in m.items() if k != "_rx"} for m in self.maneuvers
                    if now - m["_rx"] <= MANEUVER_MAX_AGE_S]
            self.maneuvers.clear()
        return frames, mans

    def _drop_backlog(self):
        with self.lock:                              # never replay a backlog into a live twin
            self.frames.clear()
            self.maneuvers.clear()

    def run(self):
        backoff = 2.0
        while True:
            try:
                with self.connect() as conn:
                    self.stats["publisher"] = "up"
                    backoff = 2.0
                    self._drop_backlog()
                    while True:
                        time.sleep(BATCH_S)
                        frames, mans = self._take()
                        if frames or mans:
                            self.send(conn, {"v": 1, "device": self.device_id, "frames": frames, "maneuvers": mans})
                            self.stats["batches_out"] += 1
            except FileNotFoundError as e:
                self.stats["publisher"] = "no credentials"
                logger.warning("[Motion] %s: no credentials (%s) - live twin off", self.cloud, e)
                time.sleep(60)
            except Exception as e:                   # noqa: BLE001
                self.stats["publisher"] = "down"
                logger.info("[Motion] %s publisher down: %s - retrying in %.0fs", self.cloud, e, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 60.0)


class WebPubSubChannel(_Channel):
    """Azure Web PubSub: WebSocket client holding a send-to-group-only token."""
    cloud = "azure"

    def __init__(self, device_id, token_file, host, hub="motion", group="motion"):
        super().__init__(device_id)
        self.token_file, self.host, self.hub, self.group = token_file, host, hub, group

    def connect(self):
        from websockets.sync.client import connect
        with open(self.token_file) as fh:
            token = fh.read().strip()
        return connect("wss://%s/client/hubs/%s?access_token=%s" % (self.host, self.hub, token),
                       subprotocols=["json.webpubsub.azure.v1"], open_timeout=10, max_size=2**20)

    def send(self, ws, data):
        ws.send(json.dumps({"type": "sendToGroup", "group": self.group, "noEcho": True, "dataType": "json",
                            "data": data}, separators=(",", ":")))


class AppSyncChannel(_Channel):
    """AWS AppSync Events: HTTP publish signed with the Thor's send-only IAM key
    (appsync:EventPublish on namespace `motion` only)."""
    cloud = "aws"

    def __init__(self, device_id, credentials_file):
        super().__init__(device_id)
        self.credentials_file = credentials_file

    def connect(self):
        import contextlib
        import requests
        from botocore.credentials import Credentials
        with open(self.credentials_file) as f:
            c = json.load(f)
        self._creds = Credentials(c["access_key_id"], c["secret_access_key"])
        self._region, self._host, self._channel = c["region"], c["appsync_http"], c.get("channel", "/motion/booth")
        session = requests.Session()
        return contextlib.closing(session)

    def send(self, session, data):
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        url = "https://%s/event" % self._host
        body = json.dumps({"channel": self._channel, "events": [json.dumps(data, separators=(",", ":"))]},
                          separators=(",", ":"))
        req = AWSRequest(method="POST", url=url, data=body, headers={"content-type": "application/json"})
        SigV4Auth(self._creds, "appsync", self._region).add_auth(req)
        r = session.post(url, data=body, headers=dict(req.headers), timeout=5)
        if r.status_code >= 300:
            raise RuntimeError("AppSync publish HTTP %s: %s" % (r.status_code, r.text[:200]))


class MotionStream:
    def __init__(self, url_fn: Callable[[], str], session_fn: Callable, channels: List[_Channel],
                 on_maneuver: Optional[Callable[[dict], None]] = None,
                 cloud_selector: Optional[Callable[[], set]] = None):
        self.url_fn, self.session_fn = url_fn, session_fn
        self.channels = channels
        self.on_maneuver = on_maneuver
        self.cloud_selector = cloud_selector       # the conference demo profile picks the cloud path
        self.recognizer = ManeuverRecognizer()
        self.stats = {"frames_in": 0, "maneuvers": 0}

    def start(self):
        threading.Thread(target=self._read_loop, name="MotionRead", daemon=True).start()
        for ch in self.channels:
            threading.Thread(target=ch.run, name="MotionPublish-" + ch.cloud, daemon=True).start()
        logger.info("[Motion] started (channels: %s)", ", ".join(ch.cloud for ch in self.channels))
        return self

    def _active(self) -> List[_Channel]:
        if self.cloud_selector is None:
            return self.channels
        try:
            clouds = set(self.cloud_selector())
        except Exception:                            # noqa: BLE001
            return self.channels
        return [ch for ch in self.channels if ch.cloud in clouds]

    # -- robot link /joints (server-sent events) -------------------------------
    def _read_loop(self):
        while True:
            try:
                with self.session_fn().get(self.url_fn() + "/joints", stream=True, timeout=(5, 10)) as r:
                    r.raise_for_status()
                    for line in r.iter_lines(decode_unicode=True):
                        if not line or not line.startswith("data: "):
                            continue
                        f = json.loads(line[6:])
                        if not isinstance(f.get("q"), list) or len(f["q"]) != 12:
                            continue
                        m = self.recognizer.feed(f)
                        self.stats["frames_in"] += 1
                        for ch in self._active():
                            ch.offer(f, m)
                        if m:
                            self.stats["maneuvers"] += 1
                            logger.info("[Motion] maneuver %s", m)
                            if self.on_maneuver:
                                try:
                                    self.on_maneuver(m)
                                except Exception as e:      # noqa: BLE001
                                    logger.warning("[Motion] maneuver telemetry failed: %s", e)
            except Exception as e:                          # noqa: BLE001
                logger.info("[Motion] robot stream unavailable: %s - retrying in 3s", e)
            time.sleep(3)


def start_from_config(cfg: dict, device_id: str, on_maneuver=None, cloud_selector=None) -> Optional[MotionStream]:
    """cfg = config['motion_stream']: `enabled`, plus an `azure` and/or `aws` channel block."""
    if not cfg or not cfg.get("enabled"):
        return None
    channels: List[_Channel] = []
    az = cfg.get("azure") or ({"pubsub_host": cfg["pubsub_host"]} if cfg.get("pubsub_host") else None)
    if az and az.get("pubsub_host"):
        channels.append(WebPubSubChannel(device_id, az.get("token_file", cfg.get("token_file", "/state/motion.token")),
                                         az["pubsub_host"], az.get("hub", "motion"), az.get("group", "motion")))
    aws = cfg.get("aws")
    if aws:
        channels.append(AppSyncChannel(device_id, aws.get("credentials_file", "/state/aws-edge.json")))
    if not channels:
        return None
    from robot_host import robot_host
    return MotionStream(url_fn=robot_host.service_url, session_fn=robot_host.public, channels=channels,
                        on_maneuver=on_maneuver, cloud_selector=cloud_selector).start()
