#!/usr/bin/env python3
"""
Gesture Detector — YOLO11n-pose keypoint-based gesture recognition.

Runs a lightweight pose model (~6MB) on detection frames to identify
an outstretched hand gesture.  Designed to piggyback on the existing
detection pipeline with minimal added latency.

Outstretched hand heuristic:
  - Wrist is extended far horizontally from the shoulder
  - Elbow is roughly between them (arm is straight, not bent at side)
  - Keypoint confidence is above threshold (not hallucinated)
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

# Thresholds
_KP_CONF_MIN = 0.3           # minimum keypoint confidence
_ARM_EXTENSION_RATIO = 1.5   # wrist-shoulder horizontal distance must be ≥ 1.5x shoulder width
_ELBOW_STRAIGHTNESS = 0.6    # elbow must be at least 60% of the way from shoulder to wrist (arm extended)
_POSE_FRAME_DIM = 480        # resize frames for fast pose inference


class GestureDetector:
    """Lightweight pose-based gesture detector."""

    def __init__(self, model_path: str = "yolo11n-pose.pt"):
        self._model = None
        self._model_path = model_path
        self._lock = threading.Lock()
        self._loaded = False

    def _ensure_model(self):
        if self._loaded:
            return True
        with self._lock:
            if self._loaded:
                return True
            try:
                from ultralytics import YOLO
                self._model = YOLO(self._model_path)
                self._loaded = True
                logger.info(f"[GestureDetector] Pose model loaded: {self._model_path}")
                return True
            except Exception as e:
                logger.error(f"[GestureDetector] Failed to load pose model: {e}")
                return False

    def check_outstretched_hand(self, frame: np.ndarray) -> dict:
        """Run pose estimation and check for outstretched hand.

        Returns:
            dict with keys:
              - detected (bool): True if gesture found
              - confidence (float): keypoint confidence of the match
              - arm (str): 'left' or 'right' or None
              - person_count (int): number of people found
              - inference_ms (float): how long pose inference took
        """
        if not self._ensure_model():
            return {"detected": False, "confidence": 0, "arm": None,
                    "person_count": 0, "inference_ms": 0}

        # Resize for speed
        h, w = frame.shape[:2]
        if max(h, w) > _POSE_FRAME_DIM:
            scale = _POSE_FRAME_DIM / max(h, w)
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)),
                               interpolation=cv2.INTER_AREA)

        t0 = time.time()
        results = self._model(frame, verbose=False, conf=0.25)
        inference_ms = (time.time() - t0) * 1000

        if not results or len(results) == 0:
            return {"detected": False, "confidence": 0, "arm": None,
                    "person_count": 0, "inference_ms": inference_ms}

        result = results[0]
        if result.keypoints is None or result.keypoints.data is None:
            return {"detected": False, "confidence": 0, "arm": None,
                    "person_count": 0, "inference_ms": inference_ms}

        keypoints = result.keypoints.data  # shape: (N, 17, 3) — x, y, conf
        person_count = keypoints.shape[0]

        for person_kps in keypoints:
            detected, conf, arm = self._check_person_gesture(person_kps)
            if detected:
                return {"detected": True, "confidence": conf, "arm": arm,
                        "person_count": person_count, "inference_ms": inference_ms}

        return {"detected": False, "confidence": 0, "arm": None,
                "person_count": person_count, "inference_ms": inference_ms}

    def _check_person_gesture(self, kps) -> tuple:
        """Check a single person's keypoints for outstretched hand.

        Args:
            kps: tensor of shape (17, 3) — x, y, confidence

        Returns:
            (detected: bool, confidence: float, arm: str|None)
        """
        # Check both arms
        for side, (sh_idx, el_idx, wr_idx) in [
            ("left", (L_SHOULDER, L_ELBOW, L_WRIST)),
            ("right", (R_SHOULDER, R_ELBOW, R_WRIST)),
        ]:
            sh = kps[sh_idx]  # shoulder [x, y, conf]
            el = kps[el_idx]  # elbow
            wr = kps[wr_idx]  # wrist

            # All three keypoints must be confident
            sh_conf, el_conf, wr_conf = float(sh[2]), float(el[2]), float(wr[2])
            if min(sh_conf, el_conf, wr_conf) < _KP_CONF_MIN:
                continue

            # Shoulder width as a reference scale (distance between shoulders)
            other_sh = kps[R_SHOULDER if sh_idx == L_SHOULDER else L_SHOULDER]
            if float(other_sh[2]) >= _KP_CONF_MIN:
                shoulder_width = abs(float(sh[0]) - float(other_sh[0]))
            else:
                # Fallback: use a fraction of frame width as reference
                shoulder_width = 50  # rough pixel estimate

            if shoulder_width < 10:
                shoulder_width = 50  # avoid division issues with tiny values

            # Horizontal extension: wrist must be far from shoulder
            wrist_shoulder_dx = abs(float(wr[0]) - float(sh[0]))
            extension_ratio = wrist_shoulder_dx / shoulder_width

            if extension_ratio < _ARM_EXTENSION_RATIO:
                continue

            # Elbow straightness: elbow should be between shoulder and wrist
            # (not tucked at the body). Check elbow X is between shoulder X
            # and wrist X, at least 60% of the way out.
            sh_x, wr_x = float(sh[0]), float(wr[0])
            el_x = float(el[0])
            if wr_x != sh_x:
                elbow_ratio = (el_x - sh_x) / (wr_x - sh_x)
                if elbow_ratio < _ELBOW_STRAIGHTNESS:
                    continue
            # else: wrist directly above/below shoulder, skip

            avg_conf = (sh_conf + el_conf + wr_conf) / 3
            return True, round(avg_conf, 2), side

        return False, 0, None


# Module-level singleton
_detector = None


def get_gesture_detector() -> GestureDetector:
    global _detector
    if _detector is None:
        _detector = GestureDetector()
    return _detector
