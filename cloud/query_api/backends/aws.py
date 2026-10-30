"""AWS backend for re:Invent (ADR 0011): the same named operations and row shapes
as the ADX functions in deploy/azure/adx/setup.kql, read from the DynamoDB live
store (backends/aws_store.py). Read-only by construction: it only issues queries."""
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from . import aws_store as st

_TIMESPAN = re.compile(r"^(\d{1,4})([smhd])$")
_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}
STATE_CODES = (100, 1001, 1002)                  # posture states, not faults (dashboard STATE_CODES)


def _span(v: str) -> timedelta:
    m = _TIMESPAN.match(str(v))
    if not m:
        raise ValueError("timespans must look like 15m / 1h / 7d")
    return timedelta(seconds=int(m.group(1)) * _UNIT[m.group(2)])


def _avg(xs) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _max(xs):
    xs = [x for x in xs if x is not None]
    return max(xs) if xs else None


def _bin(ts: datetime, size: timedelta) -> datetime:
    s = size.total_seconds()
    return datetime.fromtimestamp(math.floor(ts.timestamp() / s) * s, tz=timezone.utc)


def _age(ts: Optional[str], now: datetime) -> Optional[int]:
    t = st.parse_ts(ts)
    return int((now - t).total_seconds()) if t else None


def _iso_ts(row: Dict) -> Dict:
    t = st.parse_ts(row.get("Timestamp"))
    if t:
        row["Timestamp"] = st.iso(t)
    return row


class AWSBackend:
    def __init__(self):
        self.r = st.Reader()

    def run(self, function_name: str, params: dict) -> list:
        fn = getattr(self, function_name, None)
        if fn is None:
            raise ValueError(f"unknown operation {function_name}")
        spans = {k: _span(v) for k, v in params.items()}
        return fn(**spans)

    # -- vitals --------------------------------------------------------------
    def Vitals_Latest(self) -> List[Dict]:
        now = datetime.now(timezone.utc)
        out = []
        for dev in self.r.devices():
            lat = self.r.latest(dev)
            v, h = lat.get("vitals"), lat.get("heartbeat")
            if v:
                row = {"DeviceId": dev, "Timestamp": v.get("Timestamp")}
                for c in ("BatterySoc", "PackVoltage", "Connected", "HasVideo", "Posture", "BodyHeight", "MotorTempMax",
                          "MotorTempAvg", "HottestJoint", "Roll", "Pitch", "ErrorCode"):
                    row[c] = v.get(c)
                row.update(DetectionFps=v.get("EdgeDetectionFps"), EdgeTempMax=v.get("EdgeTempMax"),
                           EdgeMemAvailableGb=v.get("EdgeMemAvailableGb"), LidarWindow=v.get("LidarWindow"),
                           LidarHz=v.get("LidarHz"), LidarErrorState=v.get("LidarErrorState"),
                           ObstacleAvoidance=v.get("ObstacleAvoidance"), BatteryCurrentA=v.get("BatteryCurrentA"),
                           Charging=v.get("Charging"))
            elif h:
                row = {"DeviceId": dev, "Timestamp": h.get("Timestamp"), "BatterySoc": h.get("BatterySoc"),
                       "PackVoltage": h.get("BatteryVoltage"), "Connected": h.get("RobotConnected"), "HasVideo": None,
                       "Posture": h.get("Posture"), "BodyHeight": h.get("BodyHeight"), "MotorTempMax": h.get("MotorTempMax"),
                       "MotorTempAvg": None, "HottestJoint": "", "Roll": None, "Pitch": None, "ErrorCode": None,
                       "DetectionFps": h.get("DetectionFps"), "EdgeTempMax": None, "EdgeMemAvailableGb": None,
                       "LidarWindow": "", "LidarHz": None, "LidarErrorState": None, "ObstacleAvoidance": None,
                       "BatteryCurrentA": None, "Charging": None}
            else:
                continue
            row["AgeSeconds"] = _age(row["Timestamp"], now)
            out.append(_iso_ts(row))
        return out

    def Vitals_Snapshot(self) -> List[Dict]:
        now = datetime.now(timezone.utc)
        out = []
        for dev in self.r.devices():
            v = self.r.latest(dev).get("vitals")
            if v:
                out.append(_iso_ts(dict(v, AgeSeconds=_age(v.get("Timestamp"), now))))
        return out

    def Vitals_Series(self, window: timedelta, bin_size: timedelta) -> List[Dict]:
        out = []
        for dev in self.r.devices():
            bins: Dict[datetime, List[Dict]] = {}
            for r in self.r.window("Vitals", dev, window):
                t = st.parse_ts(r.get("Timestamp"))
                if t:
                    bins.setdefault(_bin(t, bin_size), []).append(r)
            for b, rs in sorted(bins.items()):
                conn = [int(r["Connected"]) for r in rs if r.get("Connected") is not None]
                out.append({"Timestamp": st.iso(b), "DeviceId": dev,
                            "BatterySoc": _avg(r.get("BatterySoc") for r in rs),
                            "DetectionFps": _avg(r.get("EdgeDetectionFps") for r in rs),
                            "MotorTempMax": _max(r.get("MotorTempMax") for r in rs),
                            "Connected": max(conn) if conn else None,
                            "BatteryCurrentA": _avg(r.get("BatteryCurrentA") for r in rs)})
        return out

    def Posture_Timeline(self, window: timedelta) -> List[Dict]:
        rows = []
        for dev in self.r.devices():
            rows += self.r.window("Vitals", dev, window)
        rows.sort(key=lambda r: st.parse_ts(r.get("Timestamp")) or datetime.min.replace(tzinfo=timezone.utc))
        out, prev = [], ""
        for r in rows:                              # KQL prev(Posture) over the whole ordered set
            p = r.get("Posture") or ""
            if p != prev:
                out.append(_iso_ts({"Timestamp": r.get("Timestamp"), "DeviceId": r.get("DeviceId"), "Posture": p,
                                    "BodyHeight": r.get("BodyHeight")}))
            prev = p
        return out

    # -- joints --------------------------------------------------------------
    _MOTOR_COLS = ("DeviceId", "Joint", "Leg", "Segment", "Temperature", "TorqueEst", "Position", "Velocity", "Lost", "Timestamp")

    def Motors_Latest(self) -> List[Dict]:
        out = []
        for dev in self.r.devices():
            out += [_iso_ts({c: s.get(c) for c in self._MOTOR_COLS}) for s in self.r.joint_states(dev)]
        return sorted(out, key=lambda r: (r.get("Leg") or "", r.get("Segment") or ""))

    def Motors_Series(self, window: timedelta, bin_size: timedelta) -> List[Dict]:
        bins: Dict[tuple, List[list]] = {}
        for dev in self.r.devices():
            for r in self.r.window("Motors", dev, window):
                t = st.parse_ts(r.get("Timestamp"))
                if not t:
                    continue
                b = _bin(t, bin_size)
                for joint, (temp, torque) in (r.get("J") or {}).items():
                    bins.setdefault((b, joint), []).append([temp, torque])
        return [{"Timestamp": st.iso(b), "Joint": j, "Temperature": _max(x[0] for x in vs),
                 "TorqueAbs": _avg(abs(x[1]) for x in vs if x[1] is not None)} for (b, j), vs in sorted(bins.items())]

    # -- events --------------------------------------------------------------
    def Detections_Summary(self, window: timedelta) -> List[Dict]:
        by: Dict[str, List[Dict]] = {}
        for dev in self.r.devices():
            for d in self.r.window("Detections", dev, window):
                by.setdefault(d.get("ClassName") or "", []).append(d)
        out = [{"ClassName": c, "Count": len(ds), "AvgConfidence": round(_avg(d.get("Confidence") for d in ds) or 0, 3),
                "LastSeen": st.iso(max(st.parse_ts(d["Timestamp"]) for d in ds))} for c, ds in by.items()]
        return sorted(out, key=lambda r: -r["Count"])

    def _recent(self, kind: str, window: timedelta, cols) -> List[Dict]:
        rows = []
        for dev in self.r.devices():
            rows += self.r.window(kind, dev, window, newest_first=True, limit=50)
        rows.sort(key=lambda r: r.get("Timestamp") or "", reverse=True)
        return [_iso_ts({c: r.get(c) for c in cols}) for r in rows[:50]]

    def Alerts_Recent(self, window: timedelta) -> List[Dict]:
        return self._recent("Alerts", window, ("Timestamp", "DeviceId", "AlertType", "DetectionCount"))

    def Commands_Recent(self, window: timedelta) -> List[Dict]:
        return self._recent("Commands", window, ("Timestamp", "DeviceId", "SessionId", "Command", "Success", "Message"))

    def Maneuvers_Recent(self, window: timedelta) -> List[Dict]:
        return self._recent("Maneuvers", window, ("Timestamp", "DeviceId", "Name", "Detail"))

    # -- overwatch -----------------------------------------------------------
    def Overwatch_Findings(self) -> List[Dict]:
        """Port of Overwatch_Findings: terse EICAS lines, the agent adds the explanation."""
        now = datetime.now(timezone.utc)
        out: List[Dict] = []
        latest = self.Vitals_Latest()
        by_dev = {v["DeviceId"]: v for v in latest}
        for v in latest:
            dev, age = v["DeviceId"], v.get("AgeSeconds")
            if age is not None and age > 120:
                out.append({"DeviceId": dev, "Severity": "high", "Finding": f"No telemetry for {age} s"})
            soc = v.get("BatterySoc")
            if soc is not None and soc < 20:
                out.append({"DeviceId": dev, "Severity": "high" if soc < 10 else "medium", "Finding": f"Battery {int(soc)} %"})
        for dev in by_dev:
            for s in self.r.joint_states(dev):
                t = s.get("Temperature")
                if t is None or t < st.CAUTION_C:
                    continue
                out.append({"DeviceId": dev, "Severity": "high" if t >= st.LIMIT_C else "medium",
                            "Finding": self._hot_line(s, by_dev.get(dev) or {}, now)})
        for v in latest:
            dev = v["DeviceId"]
            if v.get("Connected") is False:
                out.append({"DeviceId": dev, "Severity": "high", "Finding": "Robot link down"})
            ec = v.get("ErrorCode")
            if ec is not None and ec != 0 and ec not in STATE_CODES:
                out.append({"DeviceId": dev, "Severity": "medium", "Finding": f"Error code {ec}"})
            if any(x is not None and abs(x) > 0.6 for x in (v.get("Roll"), v.get("Pitch"))):
                out.append({"DeviceId": dev, "Severity": "high", "Finding": "Body tilt · possible fall"})
            if (v.get("EdgeTempMax") or 0) > 85:
                out.append({"DeviceId": dev, "Severity": "medium", "Finding": f"Thor {int(v['EdgeTempMax'])} °C"})
            fresh = (v.get("AgeSeconds") or 0) <= 120
            if fresh and v.get("LidarWindow") == "obstructed":
                out.append({"DeviceId": dev, "Severity": "medium", "Finding": "Lidar window obstructed"})
            hz, err = v.get("LidarHz"), v.get("LidarErrorState")
            if fresh and ((err is not None and err > 0) or (hz is not None and hz < 10)):
                out.append({"DeviceId": dev, "Severity": "medium", "Finding": f"Lidar degraded · {hz} Hz"})
        for dev in by_dev:
            ppe = [a for a in self.r.window("Alerts", dev, timedelta(minutes=15)) if "ppe" in (a.get("AlertType") or "")]
            if ppe:
                out.append({"DeviceId": dev, "Severity": "medium", "Finding": f"{len(ppe)} PPE alerts · 15 min"})
        return out

    @staticmethod
    def _hot_line(s: Dict, v: Dict, now: datetime) -> str:
        t = s["Temperature"]
        ts = st.parse_ts(s.get("Timestamp"))
        trail = [p for p in s.get("Trail") or [] if now.timestamp() - p[0] <= 600]
        trend = ""
        if trail and ts:
            t0_epoch, t0 = trail[0]
            win = round((ts.timestamp() - t0_epoch) / 60)
            d = t - t0
            if win >= 1:
                trend = " · steady" if abs(d) < 1 else f" · {'+' if d > 0 else '−'}{round(abs(d))}° in {win} min"
        since = st.parse_ts(s.get("Since70") if t >= st.LIMIT_C else s.get("Since55"))
        held = f" · {int((now - since).total_seconds() // 60)} min {'over limit' if t >= st.LIMIT_C else 'in caution'}" if since else ""
        posture = v.get("Posture") or ""
        ctx = f" · {'sitting' if posture == 'low' else posture}{', charging' if v.get('Charging') is True else ''}"
        return f"{(s.get('Joint') or '').replace('_', ' ')} {int(t)} °C{trend}{held}{ctx}"
