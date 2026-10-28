"""Provider adapters for the telemetry query API.

Every backend implements the same read-only operations with the same result
shape (a list of dicts), so the agent tool and dashboards never change when
the cloud does: Azure Data Explorer for Ignite, AWS for re:Invent.
"""
import os

OPERATIONS = {
    # name: (backend function name, allowed parameters with defaults)
    "vitals_latest": ("Vitals_Latest", {}),
    "vitals_series": ("Vitals_Series", {"window": "1h", "bin_size": "1m"}),
    "detections_summary": ("Detections_Summary", {"window": "1h"}),
    "alerts_recent": ("Alerts_Recent", {"window": "1h"}),
    "commands_recent": ("Commands_Recent", {"window": "1h"}),
    "overwatch_findings": ("Overwatch_Findings", {}),
    "motors_latest": ("Motors_Latest", {}),
    "motors_series": ("Motors_Series", {"window": "1h", "bin_size": "1m"}),
    "posture_timeline": ("Posture_Timeline", {"window": "1h"}),
}


def get_backend():
    kind = os.environ.get("TELEMETRY_BACKEND", "adx").lower()
    if kind == "adx":
        from .adx import ADXBackend
        return ADXBackend()
    if kind == "aws":
        from .aws import AWSBackend
        return AWSBackend()
    raise ValueError(f"unknown TELEMETRY_BACKEND {kind!r}")
