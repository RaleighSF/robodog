"""Synthetic schema-1.1 events built with the real TelemetryManager (local sink),
emitted as JSON lines for an ADX inline-ingest test. Clearly SAMPLE data
(device_id watchdog-sample) so it can be purged before the shows."""
import json, sys, random, glob, os, shutil
from datetime import datetime, timedelta, timezone
sys.path.insert(0, ".")
import telemetry_exporter as t
out = os.environ.get("SAMPLE_OUT", "/tmp/watchdog_sample_tel")
shutil.rmtree(out, ignore_errors=True)
m = t.TelemetryManager({"telemetry": {"enabled": True, "sinks": ["local"], "local_export_dir": out,
                                      "device_id": "watchdog-sample", "device_type": "nvidia_agx_thor"}})
joints = ["FR_hip","FR_thigh","FR_calf","FL_hip","FL_thigh","FL_calf","RR_hip","RR_thigh","RR_calf","RL_hip","RL_thigh","RL_calf"]
now = datetime.now(timezone.utc); events = []
for i in range(24):                                   # 2 minutes of 5 s vitals
    ts = now - timedelta(seconds=5 * (23 - i))
    standing = i >= 6
    motors = [{"joint": j, "mode": 1, "q": round(random.uniform(-1, 1), 3), "dq": 0.0, "ddq": 0.0,
               "tau_est": round(random.uniform(0.5, 6) if standing else 0.2, 2),
               "temperature": 34 + (k % 3) + (i // 3 if j == "RL_calf" and standing else 0), "lost": 0} for k, j in enumerate(joints)]
    temps = [x["temperature"] for x in motors]; hot = max(motors, key=lambda x: x["temperature"])
    v = {"connected": True, "has_video": True, "posture": "standing" if standing else "lying",
         "sport": {"mode": 1 if standing else 0, "gait_type": 0, "error_code": 0, "body_height": 0.32 if standing else 0.08,
                   "velocity": [0.0, 0.0, 0.0], "yaw_speed": 0.0, "range_obstacle": [2.1, 1.8, 2.5, 1.9]},
         "imu": {"rpy": [0.01, -0.02, 1.57], "temperature": 41},
         "power": {"power_v": 29.8 - i * 0.01, "power_a": -2.5, "bms": {"soc": 78 - i // 8, "current": -2500, "cycle": 42,
                   "bq_ntc": [31, 32], "mcu_ntc": [35, 36]}},
         "board_temps": {"ntc1": 38, "ntc2": 39}, "feet": {"force": [60, 58, 61, 59] if standing else [0, 0, 0, 0]},
         "motors": motors, "motor_summary": {"temp_max": max(temps), "temp_avg": round(sum(temps) / 12, 1),
                                              "hottest_joint": hot["joint"], "lost_total": 0}}
    m.emit_vitals(v, {"cpu_percent": 18.0, "mem_available_gb": 10.2, "temp_max_c": 55.0, "detection_fps": 14.1})
    ev = m._buffer.pop(); ev.timestamp = ts.strftime("%Y-%m-%dT%H:%M:%S.000Z"); events.append(ev.to_dict())
m.emit_heartbeat({"soc": 76, "voltage": 29.6, "current": -2500, "connected": True, "posture": "standing", "body_height": 0.32, "motor_temp_max": 45},
                 {"detection_fps": 14.1, "stream_active": True, "detection_worker_alive": True, "go2_service_reachable": True})
events.append(m._buffer.pop().to_dict())
for e in events[-1:]: pass
det = {"schema_version": "1.1.0", "event_id": "evt_sample_det1", "event_type": "detection", "deployment_id": "watchdog-demo",
       "session_id": events[0]["session_id"], "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "device": events[0]["device"],
       "robot": events[-1]["robot"], "vision": {"detector": "yoloe", "detection_count": 2, "detections": [
           {"class_name": "person", "class_id": 0, "confidence": 0.91, "bbox": {"x": 400, "y": 200, "w": 120, "h": 300}},
           {"class_name": "person", "class_id": 0, "confidence": 0.84, "bbox": {"x": 700, "y": 220, "w": 110, "h": 280}}]}}
alert = dict(det, event_id="evt_sample_ppe1", event_type="alert:ppe_violation")
cmd = dict(events[-1], event_id="evt_sample_cmd1", event_type="command")
cmd["robot"] = dict(cmd["robot"], last_command={"command": "shake", "issued_at": cmd["timestamp"], "success": True, "message": "ok"})
events += [det, alert, cmd]
print("\n".join(json.dumps(e, separators=(",", ":"), default=str) for e in events))
