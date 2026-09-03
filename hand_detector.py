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
import threading
import time

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_MODEL_PATH = "yolov8s-worldv2.pt"
_HAND_CLASSES = ["hand", "open hand", "palm", "raised hand"]
_CONF = 0.15               # hands are small/awkward; keep recall up, gate on size
_FRAME_DIM = 640

# Tunable at runtime via POST /api/gesture
DEFAULTS = {
    "min_area_frac": 0.045,   # hand bbox as fraction of frame area
    "center_band": 0.90,      # hand centre must be within this central fraction
    "min_conf": 0.20,         # detection confidence floor
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
        try:
            res = self._model(small, verbose=False, conf=_CONF)[0]
        except Exception as e:
            logger.warning("[HandDetector] inference error: %s", e)
            out["reason"] = "inference_error"
            self.last = out
            return out
        out["inference_ms"] = (time.time() - t0) * 1000

        if res.boxes is None or len(res.boxes) == 0:
            out["reason"] = "no_hand_seen"
            self.last = out
            return out

        sh, sw = small.shape[:2]
        best = None
        for bb, cf in zip(res.boxes.xyxy.cpu().numpy(), res.boxes.conf.cpu().numpy()):
            x1, y1, x2, y2 = bb
            area = ((x2 - x1) * (y2 - y1)) / float(sw * sh)
            if best is None or area > best[0]:
                best = (area, float(cf), (x1, y1, x2, y2))

        area, conf, (x1, y1, x2, y2) = best
        out["area_frac"] = round(area, 4)
        out["confidence"] = round(conf, 2)

        if conf < self.cfg["min_conf"]:
            out["reason"] = f"low_conf({conf:.2f})"
            self.last = out
            return out

        cx = (x1 + x2) / 2.0 / sw
        half = self.cfg["center_band"] / 2.0
        if abs(cx - 0.5) > half:
            out["reason"] = "off_centre"
            self.last = out
            return out

        # THE gate: is the hand a large part of the frame (i.e. near the camera)?
        if area < self.cfg["min_area_frac"]:
            out["reason"] = f"too_small({area*100:.1f}%<{self.cfg['min_area_frac']*100:.1f}%)"
            self.last = out
            return out

        crop = small[max(0, int(y1)):int(y2), max(0, int(x1)):int(x2)]
        out["fingers"] = self.count_extended_fingers(crop)
        if self.cfg["require_open"] and 0 <= out["fingers"] < self.cfg["min_fingers"]:
            out["reason"] = f"not_open({out['fingers']} fingers)"
            self.last = out
            return out

        out["detected"] = True
        out["reason"] = "open_hand_near_camera"
        self.last = out
        logger.info("[HandDetector] HAND area=%.1f%% conf=%.2f fingers=%s -> trigger",
                    area * 100, conf, out["fingers"])
        return out


_hd = None


def get_hand_detector() -> HandDetector:
    global _hd
    if _hd is None:
        _hd = HandDetector()
    return _hd
