#!/usr/bin/env python3
"""Detect an open hand presented CLOSE to the robot's camera.

Why not pose keypoints: COCO-17 has a single `wrist` point and no fingers, so a
pose model cannot tell an open palm from a fist, nor a hand at the lens from a
hand across the room except by inference. Why not MediaPipe: the real 21-landmark
build is not installable on this platform (Python 3.8 / aarch64).

So we use YOLO-World, which is already loaded for PPE, prompted with hand text
classes. The trigger condition is deliberately simple and matches the operator's
intent: an open hand whose bounding box occupies a large fraction of the frame,
i.e. a hand held out near the dog.

NOTE ON FINGERS: this detects an open hand, it does not literally count five
fingers. `count_extended_fingers()` provides an optional convexity-defect check
to separate an open palm from a fist; it is lighting-sensitive and is used only
as a soft signal, never as a hard gate.
"""
import logging
import os
import threading
import time

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_MODEL_PATH = "yolov8s-worldv2.pt"
# MediaPipe hand landmarker (Thor image bakes it in; absent on the AGX, where the
# detector falls back to YOLO-World alone). A/B on live frames 2026-09-23: MediaPipe
# is precise (21 landmarks on the real hand, even blurred) but misses some poses;
# YOLO-World catches different poses with junk boxes mixed in. They miss at
# different moments, so a frame qualifies if EITHER finds a presented hand.
_MP_MODEL = os.environ.get("WATCHDOG_HAND_LANDMARKER", "/opt/models/hand_landmarker.task")
_HAND_CLASSES = ["hand", "open hand", "palm", "raised hand"]
_CONF = 0.15               # YOLO-World inference floor (fallback path only)
# Raleigh's rule (2026-09-23): in gesture mode ANY hand that is a substantial part
# of the view shakes; a passer-by's hand is small.
# Measured on the Thor (ultralytics 8.4) the same day: YOLO-World cannot separate a
# presented hand (0.14-0.16 @ 7-12%) from body/chair boxes (0.11-0.17 @ 34-39%) —
# loosening it produced a false-shake spree. MediaPipe's landmarker had ZERO hits
# with the hand down and put landmarks on the real hand when presented. So where
# MediaPipe is available (Thor) it alone decides; YOLO-World with its AGX-tuned
# thresholds is the fallback only where MediaPipe is missing (AGX, ultralytics 8.3).
_FRAME_DIM = 640

# Tunable at runtime via POST /api/gesture
DEFAULTS = {
    # YOLO-World fallback (AGX): tuned there, where a presented hand scores 0.4-0.6.
    "min_area_frac": 0.020,
    "max_area_frac": 0.60,    # scene-sized boxes are never a hand
    "center_band": 0.90,      # hand centre must be within this central fraction
    "min_conf": 0.35,
    # MediaPipe (primary where available): landmark-outline area is tighter than a
    # box; a hand held out at 2-3 ft measured 5-10%, a passer-by's well under 2%.
    "mp_min_area_frac": 0.025,
    "mp_votes_needed": 2,     # qualifying frames among the last mp_vote_window
    "mp_vote_window": 4,
    "require_open": False,    # if True, also require the finger heuristic to pass
    "min_fingers": 3,         # extended-finger count when require_open is on
}


class HandDetector:
    def __init__(self, model_path: str = _MODEL_PATH):
        self._model = None
        self._model_path = model_path
        self._lock = threading.Lock()
        self._loaded = False
        self._device = "cpu"
        self.cfg = dict(DEFAULTS)
        self.last = {"reason": "never_run"}
        self._mp = None
        self._mp_state = "unloaded"        # unloaded | ready | unavailable
        # Smooth flicker: fire when >=2 of the last 3 frames qualify. YOLO-World
        # hand confidence bounces frame-to-frame, so a raw single-frame gate
        # drops in and out even with a hand held steady.
        from collections import deque
        self._recent = deque(maxlen=3)
        self._mp_recent = deque(maxlen=int(self.cfg.get("mp_vote_window", 4)))

    @property
    def device(self):
        return self._device

    def _ensure(self) -> bool:
        if self._loaded:
            return True
        with self._lock:
            if self._loaded:
                return True
            try:
                from ultralytics import YOLO
                self._model = YOLO(self._model_path)
                # set_classes runs CLIP text encoding once (~1.5s); do it at load
                # so per-frame inference stays at ~26ms.
                self._model.set_classes(_HAND_CLASSES)
                try:
                    import torch
                    self._device = "cuda" if torch.cuda.is_available() else "cpu"
                except Exception:
                    self._device = "cpu"
                self._model.to(self._device)
                self._loaded = True
                logger.info("[HandDetector] loaded on %s, classes=%s", self._device, _HAND_CLASSES)
                return True
            except Exception as e:
                logger.error("[HandDetector] load failed: %s", e)
                return False

    @staticmethod
    def count_extended_fingers(crop: np.ndarray) -> int:
        """Rough extended-finger count via convex-hull defects. Soft signal only."""
        try:
            if crop.size == 0 or min(crop.shape[:2]) < 24:
                return -1
            g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            g = cv2.GaussianBlur(g, (5, 5), 0)
            _, th = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not cnts:
                return -1
            c = max(cnts, key=cv2.contourArea)
            if cv2.contourArea(c) < 0.15 * crop.shape[0] * crop.shape[1]:
                return -1
            hull = cv2.convexHull(c, returnPoints=False)
            if hull is None or len(hull) < 4:
                return -1
            defects = cv2.convexityDefects(c, np.sort(hull[:, 0])[::-1].reshape(-1, 1))
            if defects is None:
                return 0
            n = 0
            for i in range(defects.shape[0]):
                s, e, f, d = defects[i, 0]
                if d / 256.0 > 0.06 * max(crop.shape[:2]):
                    n += 1
            return min(n + 1, 5)
        except Exception:
            return -1

    def detect(self, frame: np.ndarray) -> dict:
        out = {"detected": False, "area_frac": 0.0, "confidence": 0.0,
               "fingers": -1, "inference_ms": 0.0, "reason": "no_model"}
        if not self._ensure():
            self.last = out
            return out

        fh, fw = frame.shape[:2]
        scale = 1.0
        small = frame
        if max(fh, fw) > _FRAME_DIM:
            scale = _FRAME_DIM / max(fh, fw)
            small = cv2.resize(frame, (int(fw * scale), int(fh * scale)), interpolation=cv2.INTER_AREA)

        t0 = time.time()
        mp_hit = self._mediapipe_hand(small)
        if self._mp_state == "ready":
            # MediaPipe alone decides (no YOLO-World fallback: its false boxes
            # are indistinguishable from real hands on this ultralytics).
            out["source"] = "mediapipe"
            out["inference_ms"] = (time.time() - t0) * 1000
            ok = False
            if mp_hit is None:
                out["reason"] = "no_hand_seen"
            else:
                area, cx = mp_hit
                out["area_frac"] = round(area, 4); out["confidence"] = 1.0
                if abs(cx - 0.5) > self.cfg["center_band"] / 2.0:
                    out["reason"] = "off_centre"
                elif area < self.cfg["mp_min_area_frac"]:
                    out["reason"] = "too_small(%.1f%%<%.1f%%)" % (area * 100, self.cfg["mp_min_area_frac"] * 100)
                else:
                    ok = True
            self._mp_recent.append(ok)
            need = self.cfg["mp_votes_needed"]
            if ok and sum(self._mp_recent) >= need:
                out["detected"] = True
                out["reason"] = "open_hand_near_camera"
                logger.info("[HandDetector] HAND (mediapipe) area=%.1f%% -> trigger", out["area_frac"] * 100)
            elif ok:
                out["reason"] = "confirming(%d/%d)" % (sum(self._mp_recent), need)
            self.last = out
            return out
        try:
            res = self._model(small, verbose=False, conf=_CONF)[0]
        except Exception as e:
            logger.warning("[HandDetector] inference error: %s", e)
            out["reason"] = "inference_error"
            self.last = out
            return out
        out["inference_ms"] = (time.time() - t0) * 1000

        if res.boxes is None or len(res.boxes) == 0:
            self._recent.append(False)
            out["reason"] = "no_hand_seen"
            self.last = out
            return out

        sh, sw = small.shape[:2]
        best = None
        for bb, cf in zip(res.boxes.xyxy.cpu().numpy(), res.boxes.conf.cpu().numpy()):
            x1, y1, x2, y2 = bb
            area = ((x2 - x1) * (y2 - y1)) / float(sw * sh)
            if area > self.cfg.get("max_area_frac", 0.60):
                continue                      # a scene-sized box is not a hand
            # Most confident plausible hand wins (not merely the biggest box).
            if best is None or float(cf) > best[1]:
                best = (area, float(cf), (x1, y1, x2, y2))
        if best is None:
            self._recent.append(False)
            out["reason"] = "no_hand_seen"
            self.last = out
            return out

        area, conf, (x1, y1, x2, y2) = best
        out["area_frac"] = round(area, 4)
        out["confidence"] = round(conf, 2)

        if conf < self.cfg["min_conf"]:
            out["reason"] = f"low_conf({conf:.2f})"
            self._recent.append(False)  # decay stale vote
            self.last = out
            return out

        cx = (x1 + x2) / 2.0 / sw
        half = self.cfg["center_band"] / 2.0
        if abs(cx - 0.5) > half:
            out["reason"] = "off_centre"
            self._recent.append(False)  # decay stale vote
            self.last = out
            return out

        # THE gate: is the hand a large part of the frame (i.e. near the camera)?
        if area < self.cfg["min_area_frac"]:
            out["reason"] = f"too_small({area*100:.1f}%<{self.cfg['min_area_frac']*100:.1f}%)"
            self._recent.append(False)  # decay stale vote
            self.last = out
            return out

        crop = small[max(0, int(y1)):int(y2), max(0, int(x1)):int(x2)]
        out["fingers"] = self.count_extended_fingers(crop)
        if self.cfg["require_open"] and 0 <= out["fingers"] < self.cfg["min_fingers"]:
            out["reason"] = f"not_open({out['fingers']} fingers)"
            self._recent.append(False)  # decay stale vote
            self.last = out
            return out

        out["source"] = "yolo-world"
        return self._vote(out, area, conf)

    def _vote(self, out, area, conf):
        """This frame passed every gate; record a vote and fire on a 2-of-3 majority."""
        self._recent.append(True)
        if sum(self._recent) >= 2:
            out["detected"] = True
            out["reason"] = "open_hand_near_camera"
            logger.info("[HandDetector] HAND (%s) area=%.1f%% conf=%.2f -> trigger",
                        out.get("source"), area * 100, conf)
        else:
            out["reason"] = "confirming(%d/3)" % sum(self._recent)
        self.last = out
        return out

    def _mediapipe_hand(self, small_bgr):
        """(landmark-outline area fraction, centre x) of the largest hand, or None.
        Never raises: any MediaPipe problem disables it and YOLO-World carries on."""
        if self._mp_state == "unavailable":
            return None
        try:
            if self._mp_state == "unloaded":
                if not os.path.isfile(_MP_MODEL):
                    raise FileNotFoundError(_MP_MODEL)
                import mediapipe as mp
                from mediapipe.tasks import python as mpt
                from mediapipe.tasks.python import vision
                self._mp_mod = mp
                self._mp = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
                    base_options=mpt.BaseOptions(model_asset_path=_MP_MODEL), num_hands=2,
                    min_hand_detection_confidence=0.3, min_hand_presence_confidence=0.3,
                    min_tracking_confidence=0.3, running_mode=vision.RunningMode.IMAGE))
                self._mp_state = "ready"
                logger.info("[HandDetector] MediaPipe hand landmarker loaded (%s)", _MP_MODEL)
            rgb = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2RGB)
            with self._lock:
                res = self._mp.detect(self._mp_mod.Image(image_format=self._mp_mod.ImageFormat.SRGB, data=rgb))
            best = None
            for lm in res.hand_landmarks:
                xs = [p.x for p in lm]; ys = [p.y for p in lm]
                area = (max(xs) - min(xs)) * (max(ys) - min(ys))
                if best is None or area > best[0]:
                    best = (area, (max(xs) + min(xs)) / 2.0)
            return best
        except Exception as e:                   # noqa: BLE001
            self._mp_state = "unavailable"
            logger.info("[HandDetector] MediaPipe unavailable (%s) — YOLO-World only", e)
            return None


_hd = None


def get_hand_detector() -> HandDetector:
    global _hd
    if _hd is None:
        _hd = HandDetector()
    return _hd
