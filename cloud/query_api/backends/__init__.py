"""Provider adapters for the telemetry query API.

Every backend implements the same read-only operations with the same result
shape (a list of dicts), so the agent tool and dashboards never change when
the cloud does: Azure Data Explorer for Ignite, AWS for re:Invent.
"""
import os
import re

OPERATIONS = {
    # name: (backend function name, allowed parameters with defaults)
    "vitals_latest": ("Vitals_Latest", {}),
    "vitals_snapshot": ("Vitals_Snapshot", {}),
    "vitals_series": ("Vitals_Series", {"window": "1h", "bin_size": "1m"}),
    "detections_summary": ("Detections_Summary", {"window": "1h"}),
    "alerts_recent": ("Alerts_Recent", {"window": "1h"}),
    "commands_recent": ("Commands_Recent", {"window": "1h"}),
    "overwatch_findings": ("Overwatch_Findings", {}),
    "motors_latest": ("Motors_Latest", {}),
    "motors_series": ("Motors_Series", {"window": "1h", "bin_size": "1m"}),
    "posture_timeline": ("Posture_Timeline", {"window": "1h"}),
    "maneuvers_recent": ("Maneuvers_Recent", {"window": "1h"}),
}


_TIMESPAN = re.compile(r"^(\d{1,4})([smhd])$")
_UNIT = {"s": 1, "m": 60, "h": 3600, "d": 86400}
MAX_WINDOW_S = 86400          # the live stores keep 24 h (AWS TTL) / dashboards ask for <= 1 h
MIN_BIN_S = 10
MAX_BINS = 2000


def check_params(params: dict) -> dict:
    """Validate operation parameters identically on every cloud; returns seconds per
    parameter. Raises ValueError (HTTP 400) for anything malformed or too large."""
    secs = {}
    for k, v in params.items():
        m = _TIMESPAN.match(str(v))
        if not m:
            raise ValueError(f"{k} must look like 15m / 1h / 1d")
        secs[k] = int(m.group(1)) * _UNIT[m.group(2)]
    if secs.get("window", 0) > MAX_WINDOW_S:
        raise ValueError("window must be at most 1d")
    if "bin_size" in secs:
        if secs["bin_size"] < MIN_BIN_S:
            raise ValueError("bin_size must be at least 10s")
        if secs.get("window", 3600) / secs["bin_size"] > MAX_BINS:
            raise ValueError("window / bin_size must be at most 2000 bins")
    return secs


def get_backend():
    kind = os.environ.get("TELEMETRY_BACKEND", "adx").lower()
    if kind == "adx":
        from .adx import ADXBackend
        return ADXBackend()
    if kind == "aws":
        from .aws import AWSBackend
        return AWSBackend()
    raise ValueError(f"unknown TELEMETRY_BACKEND {kind!r}")
