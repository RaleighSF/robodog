"""Live joint mirror + maneuver recognition (ADR 0010).

Reads the robot link's /joints stream (20 Hz: 12 joint angles, attitude, body
height), relays it to the cloud real-time channel in small batches so booth
dashboards can mirror the dog's motion, and recognizes maneuvers (hello/shake,
sit, stand up, lie down) from the motion itself: the dog does not report which
remote/app trick is running. Recognized maneuvers also go out as telemetry
`maneuver` events, so the agent and history see them.

Cloud channel today: Azure Web PubSub, hub `motion`, group `motion`. The Thor
holds only a send-to-group token (no access key); a dropped channel just drops
frames, since a live mirror has no use for old ones."""
import json
import logging
import os
import threading
import time
from collections import deque
from typing import Callable, Optional

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
            self._paw_since = {k: None for k in self._paw_since}
            self._cand = None
            if h is None:
                return None
        # Hello / shake: one front thigh swung well forward, held briefly, while upright.
        # One event per raise: it re-arms only after that paw comes back down.
        for idx, side in ((FR_THIGH, "front right"), (FL_THIGH, "front left")):
            if q[idx] < HELLO_THIGH_MAX and self.posture in ("standing", "low"):
                self._paw_since[idx] = self._paw_since[idx] or t
                if not self._paw_fired[idx] and t - self._paw_since[idx] >= HELLO_HOLD_S:
                    m = self._fire("hello", t, paw=side)
                    if m:
                        self._paw_fired[idx] = True
                        out = out or m
            elif q[idx] >= HELLO_THIGH_MAX:
                self._paw_since[idx] = None
                self._paw_fired[idx] = False
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


class MotionStream:
    def __init__(self, url_fn: Callable[[], str], session_fn: Callable, token_file: str,
                 pubsub_host: str, hub: str = "motion", group: str = "motion",
                 device_id: str = "", on_maneuver: Optional[Callable[[dict], None]] = None):
        self.url_fn, self.session_fn = url_fn, session_fn
        self.token_file, self.host, self.hub, self.group = token_file, pubsub_host, hub, group
        self.device_id = device_id
        self.on_maneuver = on_maneuver
        self.recognizer = ManeuverRecognizer()
        self._frames: deque = deque(maxlen=200)
        self._maneuvers: deque = deque(maxlen=20)
        self._lock = threading.Lock()
        self.stats = {"frames_in": 0, "batches_out": 0, "publisher": "down", "maneuvers": 0}

    def start(self):
        threading.Thread(target=self._read_loop, name="MotionRead", daemon=True).start()
        threading.Thread(target=self._publish_loop, name="MotionPublish", daemon=True).start()
        logger.info("[Motion] started (hub %s on %s)", self.hub, self.host)
        return self

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
                        with self._lock:
                            self._frames.append(f)
                            self.stats["frames_in"] += 1
                            if m:
                                self._maneuvers.append(m)
                                self.stats["maneuvers"] += 1
                        if m:
                            logger.info("[Motion] maneuver %s", m)
                            if self.on_maneuver:
                                try:
                                    self.on_maneuver(m)
                                except Exception as e:      # noqa: BLE001
                                    logger.warning("[Motion] maneuver telemetry failed: %s", e)
            except Exception as e:                          # noqa: BLE001
                logger.info("[Motion] robot stream unavailable: %s - retrying in 3s", e)
            time.sleep(3)

    # -- cloud channel ------------------------------------------------------------
    def _token(self) -> str:
        with open(self.token_file) as fh:
            return fh.read().strip()

    def _publish_loop(self):
        from websockets.sync.client import connect
        backoff = 2.0
        while True:
            try:
                url = "wss://%s/client/hubs/%s?access_token=%s" % (self.host, self.hub, self._token())
                with connect(url, subprotocols=["json.webpubsub.azure.v1"], open_timeout=10, max_size=2**20) as ws:
                    self.stats["publisher"] = "up"
                    backoff = 2.0
                    with self._lock:
                        self._frames.clear()                # never replay a backlog into a live twin
                        self._maneuvers.clear()
                    while True:
                        time.sleep(BATCH_S)
                        with self._lock:
                            frames, self._frames = list(self._frames), deque(maxlen=200)
                            newest = frames[-1]["t"] if frames else None
                            mans = [m for m in self._maneuvers
                                    if newest is None or newest - m["t"] <= MANEUVER_MAX_AGE_S]
                            self._maneuvers.clear()
                        if not frames and not mans:
                            continue
                        msg = {"type": "sendToGroup", "group": self.group, "noEcho": True, "dataType": "json",
                               "data": {"v": 1, "device": self.device_id, "frames": frames, "maneuvers": mans}}
                        ws.send(json.dumps(msg, separators=(",", ":")))
                        self.stats["batches_out"] += 1
            except FileNotFoundError:
                self.stats["publisher"] = "no token"
                logger.warning("[Motion] no publisher token at %s - live mirror off", self.token_file)
                time.sleep(60)
            except Exception as e:                          # noqa: BLE001
                self.stats["publisher"] = "down"
                logger.info("[Motion] publisher down: %s - retrying in %.0fs", e, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 60.0)


def start_from_config(cfg: dict, device_id: str, on_maneuver=None) -> Optional[MotionStream]:
    """cfg = config['motion_stream']; disabled unless `enabled: true` and a host is set."""
    if not cfg or not cfg.get("enabled") or not cfg.get("pubsub_host"):
        return None
    from robot_host import robot_host
    return MotionStream(url_fn=robot_host.service_url, session_fn=robot_host.public,
                        token_file=cfg.get("token_file", "/state/motion.token"),
                        pubsub_host=cfg["pubsub_host"], hub=cfg.get("hub", "motion"),
                        group=cfg.get("group", "motion"), device_id=device_id,
                        on_maneuver=on_maneuver).start()
