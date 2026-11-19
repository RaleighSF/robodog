"""Telemetry event -> derived rows, mirroring the ADX ingest functions in
deploy/azure/adx/setup.kql (ExpandVitals, ExpandMotors, ExpandHeartbeats,
ExpandDetections, ExpandCommands, ExpandAlerts, ExpandManeuvers) column for
column. Used by the AWS ingest Lambda so both clouds derive identical rows from
the same schema-1.2 events (cloud/PARITY.md)."""
from typing import Any, Dict, List, Optional


def _get(d: Any, *path: Any) -> Any:
    for p in path:
        if isinstance(d, dict):
            d = d.get(p)
        elif isinstance(d, list) and isinstance(p, int):
            d = d[p] if -len(d) <= p < len(d) else None
        else:
            return None
    return d


def _real(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return float(v)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _int(v: Any) -> Optional[int]:
    f = _real(v)
    return int(f) if f is not None else None


def _bool(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.lower() in ("true", "false"):
        return v.lower() == "true"
    return None


def _str(v: Any) -> str:
    return "" if v is None else str(v)


def _max_of(*vals: Any) -> Optional[float]:
    nums = [x for x in (_real(v) for v in vals) if x is not None]
    return max(nums) if nums else None


def vitals_row(ev: Dict) -> Dict:
    """ExpandVitals."""
    v = ev.get("robot_vitals") or {}
    e = ev.get("edge") or {}
    age = _real(v.get("sport_age_s"))
    sport_fresh = age is None or age <= 2.0       # attitude/height count only while sport state is fresh
    ntc = [x for x in (_real(n) for n in (_get(v, "power", "bms", "bq_ntc") or []) + (_get(v, "power", "bms", "mcu_ntc") or [])) if x is not None]
    bms_current = _real(_get(v, "power", "bms", "current"))
    return {
        "Timestamp": ev.get("timestamp"), "DeviceId": _str(_get(ev, "device", "device_id")),
        "SessionId": _str(ev.get("session_id")), "Connected": _bool(v.get("connected")),
        "HasVideo": _bool(v.get("has_video")), "Posture": _str(v.get("posture")),
        "BodyHeight": _real(_get(v, "sport", "body_height")) if sport_fresh else None,
        "SportMode": _int(_get(v, "sport", "mode")), "GaitType": _int(_get(v, "sport", "gait_type")),
        "ErrorCode": _int(_get(v, "sport", "error_code")),
        "VelocityX": _real(_get(v, "sport", "velocity", 0)), "VelocityY": _real(_get(v, "sport", "velocity", 1)),
        "YawSpeed": _real(_get(v, "sport", "yaw_speed")),
        "Roll": _real(_get(v, "imu", "rpy", 0)) if sport_fresh else None,
        "Pitch": _real(_get(v, "imu", "rpy", 1)) if sport_fresh else None,
        "Yaw": _real(_get(v, "imu", "rpy", 2)) if sport_fresh else None,
        "BatterySoc": _real(_get(v, "power", "bms", "soc")), "PackVoltage": _real(_get(v, "power", "power_v")),
        "PackCurrentA": _real(_get(v, "power", "power_a")), "BmsCycles": _int(_get(v, "power", "bms", "cycle")),
        "BmsTempMax": max(ntc) if ntc else None,
        "BoardTempMax": _max_of(_get(v, "board_temps", "ntc1"), _get(v, "board_temps", "ntc2")),
        "ImuTemp": _real(_get(v, "imu", "temperature")),
        "MotorTempMax": _real(_get(v, "motor_summary", "temp_max")), "MotorTempAvg": _real(_get(v, "motor_summary", "temp_avg")),
        "HottestJoint": _str(_get(v, "motor_summary", "hottest_joint")), "LostFrames": _int(_get(v, "motor_summary", "lost_total")),
        "FootForce": _get(v, "feet", "force"), "RangeObstacle": _get(v, "sport", "range_obstacle"),
        "EdgeCpuPercent": _real(e.get("cpu_percent")), "EdgeMemAvailableGb": _real(e.get("mem_available_gb")),
        "EdgeTempMax": _real(e.get("temp_max_c")), "EdgeDetectionFps": _real(e.get("detection_fps")),
        "LidarWindow": _str(_get(v, "lidar", "window")), "LidarRingSectors": _get(v, "lidar", "ring_sectors"),
        "LidarHz": _real(_get(v, "lidar", "cloud_hz")), "LidarErrorState": _int(_get(v, "lidar", "error_state")),
        "ObstacleAvoidance": _bool(_get(v, "lidar", "avoidance")),
        # BMS current is signed mA: + charging, - discharging.
        "BatteryCurrentA": bms_current / 1000.0 if bms_current is not None else None,
        "Charging": (bms_current > 500) if bms_current is not None else None,
        "Raw": ev,
    }


def motor_rows(ev: Dict) -> List[Dict]:
    """ExpandMotors."""
    out = []
    for m in _get(ev, "robot_vitals", "motors") or []:
        if not isinstance(m, dict):
            continue
        joint = _str(m.get("joint"))
        parts = joint.split("_")
        out.append({"Timestamp": ev.get("timestamp"), "DeviceId": _str(_get(ev, "device", "device_id")), "Joint": joint,
                    "Leg": parts[0] if parts else "", "Segment": parts[1] if len(parts) > 1 else "",
                    "Temperature": _real(m.get("temperature")), "TorqueEst": _real(m.get("tau_est")),
                    "Position": _real(m.get("q")), "Velocity": _real(m.get("dq")),
                    "Lost": _int(m.get("lost")), "Mode": _int(m.get("mode"))})
    return out


def heartbeat_row(ev: Dict) -> Dict:
    """ExpandHeartbeats."""
    r, h = ev.get("robot") or {}, ev.get("system_health") or {}
    return {"Timestamp": ev.get("timestamp"), "DeviceId": _str(_get(ev, "device", "device_id")),
            "DeviceType": _str(_get(ev, "device", "device_type")), "SessionId": _str(ev.get("session_id")),
            "RobotId": _str(r.get("robot_id")), "BatterySoc": _real(_get(r, "battery", "soc")),
            "BatteryVoltage": _real(_get(r, "battery", "voltage")), "BatteryCurrentMa": _real(_get(r, "battery", "current")),
            "RobotConnected": _bool(_get(r, "battery", "connected")), "MotionMode": _str(r.get("motion_mode")),
            "Posture": _str(r.get("posture")), "BodyHeight": _real(r.get("body_height")),
            "MotorTempMax": _real(r.get("motor_temp_max")), "DetectionFps": _real(h.get("detection_fps")),
            "FramesProcessed": _int(h.get("frames_processed")), "StreamActive": _bool(h.get("stream_active")),
            "DetectionWorkerAlive": _bool(h.get("detection_worker_alive")),
            "RobotLinkReachable": _bool(h.get("go2_service_reachable")), "UptimeSeconds": _real(h.get("uptime_seconds"))}


def detection_rows(ev: Dict) -> List[Dict]:
    """ExpandDetections (detection and alert events)."""
    et = _str(ev.get("event_type"))
    if not (et == "detection" or et.startswith("alert")):
        return []
    vis = ev.get("vision") or {}
    out = []
    for d in vis.get("detections") or []:
        if not isinstance(d, dict):
            continue
        out.append({"Timestamp": ev.get("timestamp"), "DeviceId": _str(_get(ev, "device", "device_id")),
                    "SessionId": _str(ev.get("session_id")), "EventId": _str(ev.get("event_id")),
                    "Detector": _str(vis.get("detector")), "ClassName": _str(d.get("class_name")),
                    "Confidence": _real(d.get("confidence")), "BboxX": _int(_get(d, "bbox", "x")),
                    "BboxY": _int(_get(d, "bbox", "y")), "BboxW": _int(_get(d, "bbox", "w")),
                    "BboxH": _int(_get(d, "bbox", "h")), "ImageKey": _str(vis.get("detection_image_key"))})
    return out


def command_row(ev: Dict) -> Dict:
    """ExpandCommands."""
    c = _get(ev, "robot", "last_command") or {}
    return {"Timestamp": ev.get("timestamp"), "DeviceId": _str(_get(ev, "device", "device_id")),
            "SessionId": _str(ev.get("session_id")), "Command": _str(c.get("command")),
            "Success": _bool(c.get("success")), "Message": _str(c.get("message"))}


def alert_row(ev: Dict) -> Dict:
    """ExpandAlerts (without Raw; nothing downstream reads it)."""
    return {"Timestamp": ev.get("timestamp"), "DeviceId": _str(_get(ev, "device", "device_id")),
            "SessionId": _str(ev.get("session_id")), "AlertType": _str(ev.get("event_type")),
            "EventId": _str(ev.get("event_id")), "DetectionCount": _int(_get(ev, "vision", "detection_count"))}


def maneuver_row(ev: Dict) -> Dict:
    """ExpandManeuvers."""
    m = ev.get("maneuver") or {}
    return {"Timestamp": ev.get("timestamp"), "DeviceId": _str(_get(ev, "device", "device_id")),
            "SessionId": _str(ev.get("session_id")), "Name": _str(m.get("name")),
            "Detail": {k: v for k, v in m.items() if k not in ("name", "t")}}
