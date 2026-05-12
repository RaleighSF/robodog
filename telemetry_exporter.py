#!/usr/bin/env python3
"""
Cloud-agnostic telemetry exporter for Watch Dog.

Assembles robot state, vision detections, commands, and system health
into versioned JSON events, buffers them in memory, and flushes to any
S3-compatible object store (AWS S3, GCS, MinIO, etc.).

Detection images are uploaded as separate JPEGs with keys referenced
in the JSON payload so downstream consumers (Snowflake, Athena, BigQuery)
never need to parse base64.
"""

import json
import logging
import os
import queue
import threading
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Event dataclasses
# ---------------------------------------------------------------------------

@dataclass
class BatteryState:
    soc: Optional[float] = None
    voltage: Optional[float] = None
    current: Optional[float] = None
    connected: bool = False


@dataclass
class RobotCommand:
    command: str = ""
    issued_at: str = ""
    success: Optional[bool] = None
    message: str = ""


@dataclass
class RobotState:
    robot_id: str = "go2-unit-01"
    battery: BatteryState = field(default_factory=BatteryState)
    motion_mode: str = "normal"
    last_command: Optional[RobotCommand] = None


@dataclass
class BoundingBox:
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0


@dataclass
class DetectionEntry:
    class_name: str = ""
    class_id: int = 0
    confidence: float = 0.0
    bbox: BoundingBox = field(default_factory=BoundingBox)


@dataclass
class FrameInfo:
    width: int = 0
    height: int = 0
    source_type: str = ""


@dataclass
class VisionState:
    detection_mode: str = "text"
    detector: str = "yoloe"
    model: str = "yolo11s.pt"
    confidence_threshold: float = 0.25
    iou_threshold: float = 0.45
    classes_configured: List[str] = field(default_factory=list)
    frame: FrameInfo = field(default_factory=FrameInfo)
    detections: List[DetectionEntry] = field(default_factory=list)
    detection_count: int = 0
    detection_image_key: Optional[str] = None
    thumbnail_image_key: Optional[str] = None


@dataclass
class SystemHealth:
    uptime_seconds: float = 0.0
    stream_active: bool = False
    detection_worker_alive: bool = False
    detection_fps: float = 0.0
    frames_processed: int = 0
    go2_service_reachable: bool = False
    rtsp_server_running: Optional[bool] = None


@dataclass
class DeviceInfo:
    device_id: str = ""
    device_type: str = ""
    hostname: str = ""
    platform: str = ""


@dataclass
class TelemetryEvent:
    schema_version: str = SCHEMA_VERSION
    event_id: str = ""
    event_type: str = ""  # heartbeat | detection | command | alert
    deployment_id: str = ""
    session_id: str = ""
    timestamp: str = ""
    device: DeviceInfo = field(default_factory=DeviceInfo)
    robot: RobotState = field(default_factory=RobotState)
    vision: Optional[VisionState] = None
    system_health: SystemHealth = field(default_factory=SystemHealth)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if d.get("vision") is None:
            del d["vision"]
        if d.get("robot", {}).get("last_command") is None:
            d["robot"]["last_command"] = None
        return d


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _make_event_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short_uuid = uuid.uuid4().hex[:8]
    return f"evt_{ts}_{short_uuid}"


def _hive_prefix(dt: datetime) -> str:
    return f"year={dt.year}/month={dt.month:02d}/day={dt.day:02d}/hour={dt.hour:02d}"


def _encode_thumbnail(frame: np.ndarray, max_width: int = 320, quality: int = 75) -> Optional[bytes]:
    if frame is None:
        return None
    h, w = frame.shape[:2]
    if w > max_width:
        scale = max_width / w
        frame = cv2.resize(frame, (max_width, int(h * scale)), interpolation=cv2.INTER_AREA)
    ret, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes() if ret else None


def _encode_image(frame: np.ndarray, max_width: int = 960, quality: int = 80) -> Optional[bytes]:
    if frame is None:
        return None
    h, w = frame.shape[:2]
    if w > max_width:
        scale = max_width / w
        frame = cv2.resize(frame, (max_width, int(h * scale)), interpolation=cv2.INTER_AREA)
    ret, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes() if ret else None


# ---------------------------------------------------------------------------
# S3-compatible exporter
# ---------------------------------------------------------------------------

class S3Exporter:
    """Uploads to any S3-compatible endpoint (AWS, MinIO, GCS interop)."""

    def __init__(self, bucket: str, prefix: str = "v1",
                 endpoint_url: Optional[str] = None,
                 region: str = "us-east-1",
                 access_key: Optional[str] = None,
                 secret_key: Optional[str] = None):
        self.bucket = bucket
        self.prefix = prefix
        self._client = None
        self._endpoint_url = endpoint_url
        self._region = region
        self._access_key = access_key
        self._secret_key = secret_key

    def _get_client(self):
        if self._client is None:
            import boto3
            kwargs: Dict[str, Any] = {"region_name": self._region}
            if self._endpoint_url:
                kwargs["endpoint_url"] = self._endpoint_url
            if self._access_key and self._secret_key:
                kwargs["aws_access_key_id"] = self._access_key
                kwargs["aws_secret_access_key"] = self._secret_key
            self._client = boto3.client("s3", **kwargs)
        return self._client

    def put_json(self, key: str, data: Dict) -> bool:
        try:
            full_key = f"{self.prefix}/{key}"
            body = json.dumps(data, default=str, separators=(",", ":"))
            self._get_client().put_object(
                Bucket=self.bucket, Key=full_key,
                Body=body.encode("utf-8"),
                ContentType="application/json"
            )
            return True
        except Exception as e:
            logger.error(f"[Telemetry] S3 JSON upload failed ({key}): {e}")
            return False

    def put_image(self, key: str, image_bytes: bytes) -> bool:
        try:
            full_key = f"{self.prefix}/{key}"
            self._get_client().put_object(
                Bucket=self.bucket, Key=full_key,
                Body=image_bytes,
                ContentType="image/jpeg"
            )
            return True
        except Exception as e:
            logger.error(f"[Telemetry] S3 image upload failed ({key}): {e}")
            return False


# ---------------------------------------------------------------------------
# Local file exporter (fallback / offline mode)
# ---------------------------------------------------------------------------

class LocalFileExporter:
    """Writes events to local disk as a fallback when S3 is unavailable."""

    def __init__(self, base_dir: str = "telemetry_export"):
        self.base_dir = base_dir

    def put_json(self, key: str, data: Dict) -> bool:
        try:
            path = os.path.join(self.base_dir, key)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                json.dump(data, f, default=str, indent=2)
            return True
        except Exception as e:
            logger.error(f"[Telemetry] Local JSON write failed ({key}): {e}")
            return False

    def put_image(self, key: str, image_bytes: bytes) -> bool:
        try:
            path = os.path.join(self.base_dir, key)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(image_bytes)
            return True
        except Exception as e:
            logger.error(f"[Telemetry] Local image write failed ({key}): {e}")
            return False


# ---------------------------------------------------------------------------
# TelemetryManager — the main orchestrator
# ---------------------------------------------------------------------------

class TelemetryManager:
    """
    Collects telemetry events, buffers them, and flushes to the configured
    exporter on a background thread.
    """

    def __init__(self, config: Dict[str, Any]):
        telem_cfg = config.get("telemetry", {})
        self.enabled = telem_cfg.get("enabled", False)
        self.deployment_id = telem_cfg.get("deployment_id", "watchdog-demo")
        self.heartbeat_interval = telem_cfg.get("heartbeat_interval_seconds", 30)
        self.flush_interval = telem_cfg.get("flush_interval_seconds", 10)
        self.max_buffer_size = telem_cfg.get("max_buffer_size", 100)
        self.upload_images = telem_cfg.get("upload_images", True)
        self.image_max_width = telem_cfg.get("image_max_width", 960)
        self.thumbnail_max_width = telem_cfg.get("thumbnail_max_width", 320)

        # Session ID persists across a single process lifetime
        self._session_id = f"sess_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:6]}"
        self._start_time = time.time()

        # Device info — populated once
        import platform
        self._device = DeviceInfo(
            device_id=telem_cfg.get("device_id", "watchdog-edge-01"),
            device_type=telem_cfg.get("device_type", "nvidia_agx_xavier"),
            hostname=platform.node(),
            platform=f"{platform.system().lower()}-{platform.machine()}"
        )

        # Exporter
        self._exporter = self._build_exporter(telem_cfg)

        # Event buffer (thread-safe)
        self._buffer: deque = deque(maxlen=self.max_buffer_size)
        self._image_queue: queue.Queue = queue.Queue(maxsize=50)
        self._lock = threading.Lock()

        # Background threads
        self._stop_event = threading.Event()
        self._flush_thread: Optional[threading.Thread] = None
        self._image_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None

        # Counters
        self._events_emitted = 0
        self._events_uploaded = 0
        self._events_failed = 0
        self._frames_with_detections = 0

        # Callback for heartbeat data collection
        self._heartbeat_collector = None

        if self.enabled:
            logger.info(f"[Telemetry] Enabled — deployment={self.deployment_id}, session={self._session_id}")
        else:
            logger.info("[Telemetry] Disabled by configuration")

    def _build_exporter(self, telem_cfg: Dict):
        backend = telem_cfg.get("backend", "local")
        if backend == "s3":
            return S3Exporter(
                bucket=telem_cfg.get("s3_bucket", "watchdog-telemetry"),
                prefix=telem_cfg.get("s3_prefix", "v1"),
                endpoint_url=telem_cfg.get("s3_endpoint_url"),
                region=telem_cfg.get("s3_region", "us-east-1"),
                access_key=telem_cfg.get("s3_access_key") or os.environ.get("AWS_ACCESS_KEY_ID"),
                secret_key=telem_cfg.get("s3_secret_key") or os.environ.get("AWS_SECRET_ACCESS_KEY"),
            )
        else:
            return LocalFileExporter(
                base_dir=telem_cfg.get("local_export_dir", "telemetry_export")
            )

    # -- Lifecycle -----------------------------------------------------------

    def start(self):
        if not self.enabled:
            return
        self._stop_event.clear()
        self._flush_thread = threading.Thread(target=self._flush_loop, name="TelemetryFlush", daemon=True)
        self._flush_thread.start()
        self._image_thread = threading.Thread(target=self._image_upload_loop, name="TelemetryImages", daemon=True)
        self._image_thread.start()
        logger.info("[Telemetry] Background threads started")

    def start_heartbeat(self, collector_fn):
        """Start heartbeat timer. collector_fn() should return a TelemetryEvent."""
        if not self.enabled:
            return
        self._heartbeat_collector = collector_fn
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, name="TelemetryHeartbeat", daemon=True)
        self._heartbeat_thread.start()
        logger.info(f"[Telemetry] Heartbeat started — interval={self.heartbeat_interval}s")

    def stop(self):
        self._stop_event.set()
        # Final flush
        self._flush_buffer()
        if self._flush_thread:
            self._flush_thread.join(timeout=5)
        if self._image_thread:
            self._image_thread.join(timeout=5)
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=5)
        logger.info(f"[Telemetry] Stopped — emitted={self._events_emitted}, uploaded={self._events_uploaded}, failed={self._events_failed}")

    # -- Event emission ------------------------------------------------------

    def emit_detection(self, detections: list, frame: Optional[np.ndarray],
                       robot_state: Dict, vision_config: Dict,
                       camera_source: str, frame_size: tuple):
        """Emit a detection event with optional image upload."""
        if not self.enabled:
            return

        event = self._base_event("detection")
        event.robot = self._build_robot_state(robot_state)

        det_entries = []
        for d in detections:
            bbox = d.bbox if hasattr(d, "bbox") else d.get("bbox", (0, 0, 0, 0))
            det_entries.append(DetectionEntry(
                class_name=d.class_name if hasattr(d, "class_name") else d.get("class_name", ""),
                class_id=d.class_id if hasattr(d, "class_id") else d.get("class_id", 0),
                confidence=round(d.confidence if hasattr(d, "confidence") else d.get("confidence", 0), 4),
                bbox=BoundingBox(x=int(bbox[0]), y=int(bbox[1]), w=int(bbox[2]), h=int(bbox[3]))
            ))

        w, h = frame_size if frame_size else (0, 0)
        event.vision = VisionState(
            detection_mode=vision_config.get("detection_mode", "text"),
            detector=vision_config.get("detector", "yoloe"),
            model=vision_config.get("model_path", "yolo11s.pt"),
            confidence_threshold=vision_config.get("conf", 0.25),
            iou_threshold=vision_config.get("iou", 0.45),
            classes_configured=vision_config.get("classes", []),
            frame=FrameInfo(width=w, height=h, source_type=camera_source),
            detections=det_entries,
            detection_count=len(det_entries),
        )

        # Queue image upload
        if self.upload_images and frame is not None:
            dt = datetime.now(timezone.utc)
            hive = _hive_prefix(dt)
            img_key = f"images/{hive}/{event.event_id}.jpg"
            thumb_key = f"thumbnails/{hive}/{event.event_id}.jpg"
            event.vision.detection_image_key = img_key
            event.vision.thumbnail_image_key = thumb_key
            try:
                self._image_queue.put_nowait((img_key, thumb_key, frame.copy()))
            except queue.Full:
                logger.warning("[Telemetry] Image queue full, skipping image upload")
                event.vision.detection_image_key = None
                event.vision.thumbnail_image_key = None

        self._enqueue(event)

    def emit_command(self, command: str, success: bool, message: str,
                     robot_state: Dict):
        """Emit a command event."""
        if not self.enabled:
            return
        event = self._base_event("command")
        event.robot = self._build_robot_state(robot_state)
        event.robot.last_command = RobotCommand(
            command=command,
            issued_at=_utc_now_iso(),
            success=success,
            message=message
        )
        self._enqueue(event)

    def emit_alert(self, alert_type: str, message: str, robot_state: Dict):
        """Emit an alert event (battery low, stream loss, etc.)."""
        if not self.enabled:
            return
        event = self._base_event("alert")
        event.robot = self._build_robot_state(robot_state)
        event.system_health = SystemHealth()
        # Store alert details in event_type with a sub-type
        event.event_type = f"alert:{alert_type}"
        self._enqueue(event)

    def emit_heartbeat(self, robot_state: Dict, system_health: Dict,
                       vision_config: Optional[Dict] = None):
        """Emit a heartbeat event with current system state."""
        if not self.enabled:
            return
        event = self._base_event("heartbeat")
        event.robot = self._build_robot_state(robot_state)
        event.system_health = SystemHealth(
            uptime_seconds=round(time.time() - self._start_time, 1),
            stream_active=system_health.get("stream_active", False),
            detection_worker_alive=system_health.get("detection_worker_alive", False),
            detection_fps=round(system_health.get("detection_fps", 0.0), 1),
            frames_processed=system_health.get("frames_processed", 0),
            go2_service_reachable=system_health.get("go2_service_reachable", False),
            rtsp_server_running=system_health.get("rtsp_server_running"),
        )
        if vision_config:
            event.vision = VisionState(
                detection_mode=vision_config.get("detection_mode", "text"),
                detector=vision_config.get("detector", "yoloe"),
                model=vision_config.get("model_path", "yolo11s.pt"),
                confidence_threshold=vision_config.get("conf", 0.25),
                classes_configured=vision_config.get("classes", []),
            )
        self._enqueue(event)

    # -- Internal helpers ----------------------------------------------------

    def _base_event(self, event_type: str) -> TelemetryEvent:
        return TelemetryEvent(
            event_id=_make_event_id(),
            event_type=event_type,
            deployment_id=self.deployment_id,
            session_id=self._session_id,
            timestamp=_utc_now_iso(),
            device=self._device,
        )

    def _build_robot_state(self, raw: Dict) -> RobotState:
        battery = raw.get("battery", raw)
        return RobotState(
            battery=BatteryState(
                soc=battery.get("soc"),
                voltage=battery.get("voltage"),
                current=battery.get("current"),
                connected=battery.get("connected", False),
            ),
            motion_mode=raw.get("motion_mode", "normal"),
        )

    def _enqueue(self, event: TelemetryEvent):
        with self._lock:
            self._buffer.append(event)
            self._events_emitted += 1
            count = self._events_emitted
        if count == 1 or count % 50 == 0:
            logger.info(f"[Telemetry] Events emitted: {count}")

    # -- Background loops ----------------------------------------------------

    def _flush_loop(self):
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self.flush_interval)
            self._flush_buffer()

    def _flush_buffer(self):
        events_to_flush = []
        with self._lock:
            while self._buffer:
                events_to_flush.append(self._buffer.popleft())

        for event in events_to_flush:
            dt = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
            hive = _hive_prefix(dt)
            key = f"events/{hive}/{event.event_id}.json"
            if self._exporter.put_json(key, event.to_dict()):
                self._events_uploaded += 1
            else:
                self._events_failed += 1

    def _image_upload_loop(self):
        while not self._stop_event.is_set():
            try:
                item = self._image_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            img_key, thumb_key, frame = item
            try:
                img_bytes = _encode_image(frame, max_width=self.image_max_width)
                if img_bytes:
                    self._exporter.put_image(img_key, img_bytes)
                thumb_bytes = _encode_thumbnail(frame, max_width=self.thumbnail_max_width)
                if thumb_bytes:
                    self._exporter.put_image(thumb_key, thumb_bytes)
            except Exception as e:
                logger.error(f"[Telemetry] Image processing error: {e}")
            finally:
                self._image_queue.task_done()

    def _heartbeat_loop(self):
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self.heartbeat_interval)
            if self._stop_event.is_set():
                break
            if self._heartbeat_collector:
                try:
                    self._heartbeat_collector()
                except Exception as e:
                    logger.error(f"[Telemetry] Heartbeat collector error: {e}")

    def get_stats(self) -> Dict:
        return {
            "enabled": self.enabled,
            "deployment_id": self.deployment_id,
            "session_id": self._session_id,
            "events_emitted": self._events_emitted,
            "events_uploaded": self._events_uploaded,
            "events_failed": self._events_failed,
            "buffer_size": len(self._buffer),
            "image_queue_size": self._image_queue.qsize(),
            "uptime_seconds": round(time.time() - self._start_time, 1),
        }


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_manager: Optional[TelemetryManager] = None


def init_telemetry(config: Dict[str, Any]) -> TelemetryManager:
    global _manager
    _manager = TelemetryManager(config)
    return _manager


def get_telemetry() -> Optional[TelemetryManager]:
    return _manager
