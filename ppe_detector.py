#!/usr/bin/env python3
"""
PPE Compliance Detector using YOLO-World for text-prompted detection.

Detects "hard hat" and "person" via YOLO-World text prompts, then
determines compliance by checking if each person has a hard hat nearby.

Includes temporal smoothing for stable, demo-ready output:
  - IOU-based person tracking across frames
  - Exponential moving average on box coordinates
  - Compliance voting (majority of recent frames)
"""
import logging
import threading
import time
import cv2
import numpy as np
from collections import deque
from typing import List, Dict

logger = logging.getLogger(__name__)

_PPE_MODEL_PATH = "yolov8s-worldv2.pt"
_PPE_FRAME_DIM = 640
_PPE_CONF = 0.30
_PPE_FRAME_SKIP = 2

_GREEN = (0, 200, 80)
_RED = (0, 0, 220)

_IOU_MATCH_THRESH = 0.3
_SMOOTH_ALPHA = 0.4
_VOTE_WINDOW = 5
_VOTE_THRESHOLD = 3
_TRACK_TIMEOUT = 1.5


def _iou(box_a, box_b):
    x1 = max(box_a[0], box_b[0])
    y1 = max(box_a[1], box_b[1])
    x2 = min(box_a[2], box_b[2])
    y2 = min(box_a[3], box_b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = (box_a[2] - box_a[0]) * (box_a[3] - box_a[1])
    area_b = (box_b[2] - box_b[0]) * (box_b[3] - box_b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0


class _TrackedPerson:
    def __init__(self, box, compliant):
        self.box = list(box)
        self.votes = deque(maxlen=_VOTE_WINDOW)
        self.votes.append(compliant)
        self.last_seen = time.time()
        self.confidence = 0.0

    def update(self, new_box, compliant, conf):
        for i in range(4):
            self.box[i] = self.box[i] * (1 - _SMOOTH_ALPHA) + new_box[i] * _SMOOTH_ALPHA
        self.votes.append(compliant)
        self.confidence = conf
        self.last_seen = time.time()

    @property
    def stable_compliant(self):
        if len(self.votes) < 2:
            return self.votes[-1]
        return sum(self.votes) >= _VOTE_THRESHOLD

    @property
    def is_stale(self):
        return (time.time() - self.last_seen) > _TRACK_TIMEOUT


class PPEDetector:
    """YOLO-World-based PPE compliance detector with temporal smoothing."""

    def __init__(self, model_path: str = _PPE_MODEL_PATH):
        self._model = None
        self._model_path = model_path
        self._lock = threading.Lock()
        self._loaded = False
        self._frame_counter = 0
        self._device = "cpu"
        self._consecutive_errors = 0
        self._tracks: List[_TrackedPerson] = []

    @property
    def device(self):
        return self._device

    def set_device(self, device: str):
        if device == self._device:
            return
        with self._lock:
            self._device = device
            if self._loaded and self._model is not None:
                try:
                    self._model.to(device)
                    logger.info(f"[PPEDetector] Moved model to {device}")
                except Exception as e:
                    logger.warning(f"[PPEDetector] Failed to move to {device}, falling back to cpu: {e}")
                    self._device = "cpu"
                    try:
                        self._model.to("cpu")
                    except Exception:
                        self._loaded = False
                        self._model = None

    def _ensure_model(self):
        if self._loaded:
            return True
        with self._lock:
            if self._loaded:
                return True
            try:
                from ultralytics import YOLO
                self._model = YOLO(self._model_path)
                self._model.set_classes(["person", "hard hat", "helmet", "safety helmet"])
                self._model.to(self._device)
                logger.info(f"[PPEDetector] YOLO-World loaded on {self._device}: {self._model_path}")
                self._loaded = True
                return True
            except Exception as e:
                logger.error(f"[PPEDetector] Failed to load model: {e}")
                return False

    def should_run_this_frame(self) -> bool:
        self._frame_counter += 1
        return (self._frame_counter % _PPE_FRAME_SKIP) == 0

    def detect(self, frame: np.ndarray) -> Dict:
        if not self._ensure_model():
            return {"people": [], "all_detections": [], "inference_ms": 0}

        h, w = frame.shape[:2]
        scale = 1.0
        if max(h, w) > _PPE_FRAME_DIM:
            scale = _PPE_FRAME_DIM / max(h, w)
            frame_resized = cv2.resize(
                frame, (int(w * scale), int(h * scale)),
                interpolation=cv2.INTER_AREA
            )
        else:
            frame_resized = frame

        t0 = time.time()
        try:
            results = self._model(frame_resized, verbose=False, conf=_PPE_CONF)
        except Exception as e:
            self._consecutive_errors += 1
            if self._consecutive_errors <= 3:
                logger.warning(f"[PPEDetector] Inference error ({self._consecutive_errors}): {e}")
            if self._consecutive_errors == 1 and self._device != "cpu":
                logger.warning("[PPEDetector] GPU inference failed, falling back to CPU")
                self.set_device("cpu")
            return {"people": [], "all_detections": [], "inference_ms": 0}

        self._consecutive_errors = 0
        inference_ms = (time.time() - t0) * 1000

        if not results or len(results) == 0:
            self._expire_tracks()
            return self._build_result_from_tracks(inference_ms)

        result = results[0]
        if result.boxes is None or len(result.boxes) == 0:
            self._expire_tracks()
            return self._build_result_from_tracks(inference_ms)

        boxes = result.boxes.xyxy.cpu().numpy()
        classes = result.boxes.cls.cpu().numpy().astype(int)
        confs = result.boxes.conf.cpu().numpy()
        names = result.names

        if scale != 1.0:
            boxes = boxes / scale

        persons = []
        hats = []
        all_detections = []

        for i, (box, cls, conf) in enumerate(zip(boxes, classes, confs)):
            class_name = names.get(int(cls), "?").lower()
            det = {
                "box": box.tolist(),
                "class_name": class_name,
                "confidence": float(conf),
            }
            all_detections.append(det)

            if class_name == "person":
                persons.append(det)
            elif class_name in ("hard hat", "helmet", "safety helmet"):
                hats.append(det)

        raw_people = self._assess_compliance(persons, hats, h, w)
        self._update_tracks(raw_people)

        if self._frame_counter % 30 == 0:
            logger.info(
                f"[PPEDetector] {len(persons)} person(s), {len(hats)} hat(s), "
                f"{len(self._tracks)} tracked ({inference_ms:.0f}ms)"
            )

        return self._build_result_from_tracks(inference_ms, all_detections)

    def _assess_compliance(self, persons, hats, frame_h, frame_w) -> List[Dict]:
        people = []
        used_hats = set()

        for person in persons:
            pbox = person["box"]
            px1, py1, px2, py2 = pbox
            person_h = py2 - py1
            person_w = px2 - px1

            # Head region: top 45% of person box (generous for ground-level camera)
            head_y2 = py1 + person_h * 0.45
            # Widen horizontal search by 20% of person width
            margin = person_w * 0.2
            head_x1 = px1 - margin
            head_x2 = px2 + margin

            has_hat = False
            for hi, hat in enumerate(hats):
                if hi in used_hats:
                    continue
                hbox = hat["box"]
                hx1, hy1, hx2, hy2 = hbox
                hat_cy = (hy1 + hy2) / 2
                hat_cx = (hx1 + hx2) / 2

                if hat_cy <= head_y2 and head_x1 <= hat_cx <= head_x2:
                    has_hat = True
                    used_hats.add(hi)
                    break

            people.append({
                "box": pbox,
                "compliant": has_hat,
                "confidence": person["confidence"],
            })

        return people

    def _update_tracks(self, raw_people: List[Dict]):
        matched_tracks = set()
        matched_detections = set()

        for di, person in enumerate(raw_people):
            best_iou = 0
            best_ti = -1
            for ti, track in enumerate(self._tracks):
                if ti in matched_tracks:
                    continue
                iou_val = _iou(person["box"], track.box)
                if iou_val > best_iou:
                    best_iou = iou_val
                    best_ti = ti

            if best_iou >= _IOU_MATCH_THRESH and best_ti >= 0:
                self._tracks[best_ti].update(
                    person["box"], person["compliant"], person["confidence"]
                )
                matched_tracks.add(best_ti)
                matched_detections.add(di)
            else:
                self._tracks.append(
                    _TrackedPerson(person["box"], person["compliant"])
                )
                self._tracks[-1].confidence = person["confidence"]

        self._expire_tracks()

    def _expire_tracks(self):
        self._tracks = [t for t in self._tracks if not t.is_stale]

    def _build_result_from_tracks(self, inference_ms, all_detections=None):
        people = []
        for track in self._tracks:
            compliant = track.stable_compliant
            people.append({
                "box": track.box,
                "helmet": compliant,
                "gloves": None,
                "compliant": compliant,
                "color": _GREEN if compliant else _RED,
                "confidence": track.confidence,
            })
        return {
            "people": people,
            "all_detections": all_detections or [],
            "inference_ms": inference_ms,
        }

    def draw_compliance(self, frame: np.ndarray, result: Dict) -> np.ndarray:
        annotated = frame.copy()

        for person in result.get("people", []):
            box = person["box"]
            color = person["color"]
            x1, y1, x2, y2 = int(box[0]), int(box[1]), int(box[2]), int(box[3])

            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 3)

            label = "COMPLIANT" if person["compliant"] else "NON-COMPLIANT"

            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.8
            thickness = 2
            (tw, th), baseline = cv2.getTextSize(label, font, font_scale, thickness)

            label_y = y1 - 8
            if label_y - th - 6 < 0:
                label_y = y2 + th + 8

            cv2.rectangle(annotated, (x1, label_y - th - 6), (x1 + tw + 10, label_y + 4), color, -1)
            text_color = (255, 255, 255) if not person["compliant"] else (0, 0, 0)
            cv2.putText(annotated, label, (x1 + 5, label_y),
                        font, font_scale, text_color, thickness)

        return annotated


_detector = None


def get_ppe_detector() -> PPEDetector:
    global _detector
    if _detector is None:
        _detector = PPEDetector()
    return _detector
