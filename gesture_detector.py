#!/usr/bin/env python3
"""Pose-based detection of a hand held out toward the robot.

Tuned for a Unitree Go2 camera roughly 30 cm off the floor looking UP at people.
The gesture of interest is a hand offered TOWARD the robot, which has two
consequences that earlier versions got wrong:

  1. The shoulder is frequently cropped or occluded when someone leans in, so it
     cannot be a hard requirement.
  2. An arm pointed at the lens is foreshortened, so a purely horizontal
     "wrist far from shoulder" test fails exactly when the gesture is clearest.

Prominence - how large the forearm is in frame - is therefore the primary signal.
It is what separates a hand offered to the robot from someone waving across the
room, and it is the direct expression of "predominantly in frame".
"""
import logging
import threading
import time

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# COCO keypoint indices
L_SHOULDER, R_SHOULDER = 5, 6
L_ELBOW, R_ELBOW = 7, 8
L_WRIST, R_WRIST = 9, 10

# ── Thresholds ─────────────────────────────────────────────────────
_KP_CONF_MIN = 0.30           # generic keypoint confidence floor
_WRIST_CONF_MIN = 0.45        # the wrist is the load-bearing joint; demand more
_WRIST_CONF_NO_SHOULDER = 0.55  # stricter when the shoulder is unavailable
_ARM_EXTENSION_RATIO = 1.15   # wrist-to-shoulder reach vs shoulder width
_ELBOW_STRAIGHTNESS = 0.55    # elbow at least this far along shoulder->wrist
_MIN_FOREARM_FRAC = 0.11      # elbow->wrist length as fraction of frame height
_CENTER_BAND = (0.10, 0.90)   # wrist must sit inside this horizontal band
_MIN_LATERAL_FRAC = 0.5       # wrist must be offset sideways from the shoulder by
                              # at least this fraction of shoulder width. Rejects an
                              # arm hanging straight down, which otherwise passes the
                              # 2D reach test purely on vertical separation.
_POSE_FRAME_DIM = 480         # resize frames for fast pose inference
_GESTURE_FRAME_SKIP = 2       # run pose every Nth frame


class GestureDetector:
    """Lightweight pose-based gesture detector."""

    def __init__(self, model_path: str = "yolo11n-pose.pt"):
        self._model = None
        self._model_path = model_path
        self._lock = threading.Lock()
        self._loaded = False
        self._frame_counter = 0
        self._last_reason = "none"

    @property
    def last_reason(self) -> str:
        """Why the most recent frame did or did not qualify - for tuning."""
        return self._last_reason

    def _ensure_model(self) -> bool:
        if self._loaded:
            return True
        with self._lock:
            if self._loaded:
                return True
            try:
                from ultralytics import YOLO
                self._model = YOLO(self._model_path)
                try:
                    import torch
                    if torch.cuda.is_available():
                        self._model.to("cuda")
                except Exception:
                    pass
                self._loaded = True
                logger.info("[GestureDetector] Pose model loaded: %s", self._model_path)
                return True
            except Exception as e:
                logger.error("[GestureDetector] Failed to load pose model: %s", e)
                return False

    def should_run_this_frame(self) -> bool:
        self._frame_counter += 1
        return (self._frame_counter % _GESTURE_FRAME_SKIP) == 0

    def check_outstretched_hand(self, frame: np.ndarray) -> dict:
        empty = {"detected": False, "confidence": 0, "arm": None,
                 "person_count": 0, "inference_ms": 0, "reason": "no_model"}
        if not self._ensure_model():
            return empty

        h, w = frame.shape[:2]
        if max(h, w) > _POSE_FRAME_DIM:
            scale = _POSE_FRAME_DIM / max(h, w)
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)),
                               interpolation=cv2.INTER_AREA)

        t0 = time.time()
        try:
            results = self._model(frame, verbose=False, conf=0.25)
        except Exception as e:
            logger.warning("[GestureDetector] inference failed: %s", e)
            return dict(empty, reason="inference_error")
        inference_ms = (time.time() - t0) * 1000

        if not results or results[0].keypoints is None or results[0].keypoints.data is None:
            self._last_reason = "no_pose"
            return dict(empty, inference_ms=inference_ms, reason="no_pose")

        keypoints = results[0].keypoints.data          # (N, 17, 3) -> x, y, conf
        person_count = int(keypoints.shape[0])
        fh, fw = frame.shape[:2]

        best_reason = "no_person" if person_count == 0 else "no_qualifying_arm"
        for person_kps in keypoints:
            detected, conf, arm, reason = self._check_person(person_kps, fh, fw)
            if detected:
                self._last_reason = reason
                return {"detected": True, "confidence": conf, "arm": arm,
                        "person_count": person_count,
                        "inference_ms": inference_ms, "reason": reason}
            best_reason = reason
        self._last_reason = best_reason
        return {"detected": False, "confidence": 0, "arm": None,
                "person_count": person_count,
                "inference_ms": inference_ms, "reason": best_reason}

    def _check_person(self, kps, frame_h: int, frame_w: int) -> tuple:
        reason = "low_wrist_conf"
        for side, (sh_i, el_i, wr_i) in [
            ("left", (L_SHOULDER, L_ELBOW, L_WRIST)),
            ("right", (R_SHOULDER, R_ELBOW, R_WRIST)),
        ]:
            sh, el, wr = kps[sh_i], kps[el_i], kps[wr_i]
            sh_c, el_c, wr_c = float(sh[2]), float(el[2]), float(wr[2])

            # Wrist and elbow are mandatory; shoulder is optional.
            if wr_c < _WRIST_CONF_MIN or el_c < _KP_CONF_MIN:
                continue

            wr_x, wr_y = float(wr[0]), float(wr[1])
            el_x, el_y = float(el[0]), float(el[1])

            # PROMINENCE - the "predominantly in frame" test.
            forearm_px = float(np.hypot(wr_x - el_x, wr_y - el_y))
            forearm_frac = forearm_px / max(frame_h, 1)
            if forearm_frac < _MIN_FOREARM_FRAC:
                reason = f"not_prominent({forearm_frac:.2f}<{_MIN_FOREARM_FRAC})"
                continue

            # CENTRALITY - ignore hands drifting off the edge.
            if not (_CENTER_BAND[0] * frame_w <= wr_x <= _CENTER_BAND[1] * frame_w):
                reason = "off_centre"
                continue

            if sh_c >= _KP_CONF_MIN:
                other = kps[R_SHOULDER if sh_i == L_SHOULDER else L_SHOULDER]
                sw = (abs(float(sh[0]) - float(other[0]))
                      if float(other[2]) >= _KP_CONF_MIN else 0.0)
                if sw < 10:
                    sw = max(forearm_px, 50.0)
                sh_x, sh_y = float(sh[0]), float(sh[1])
                # Full 2D reach, not just horizontal: a hand toward the lens
                # separates from the shoulder vertically as much as sideways.
                if float(np.hypot(wr_x - sh_x, wr_y - sh_y)) / sw < _ARM_EXTENSION_RATIO:
                    reason = "arm_not_extended"
                    continue
                # An arm hanging at the side clears the 2D reach test on vertical
                # distance alone. Require real sideways displacement too.
                if abs(wr_x - sh_x) / sw < _MIN_LATERAL_FRAC:
                    reason = "arm_at_side"
                    continue
                if abs(wr_x - sh_x) > 1e-3:
                    if ((el_x - sh_x) / (wr_x - sh_x)) < _ELBOW_STRAIGHTNESS:
                        reason = "elbow_tucked"
                        continue
                conf = (sh_c + el_c + wr_c) / 3.0
                method = "full_arm"
            else:
                # Shoulder cropped. Prominence and centrality already did the work.
                if wr_c < _WRIST_CONF_NO_SHOULDER:
                    reason = "no_shoulder_and_weak_wrist"
                    continue
                conf = (el_c + wr_c) / 2.0
                method = "forearm_toward"

            logger.info("[GestureDetector] %s hand via %s - forearm %.0f%% of frame, wrist conf %.2f",
                        side, method, forearm_frac * 100, wr_c)
            return True, round(conf, 2), side, method
        return False, 0, None, reason


_detector = None


def get_gesture_detector() -> GestureDetector:
    global _detector
    if _detector is None:
        _detector = GestureDetector()
    return _detector
