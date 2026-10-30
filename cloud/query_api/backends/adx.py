"""Azure Data Explorer backend: calls ONLY the named functions from
deploy/azure/adx/setup.kql (no free-form KQL), so it is read-only by
construction even if the agent is prompted to do otherwise."""
import math
import os
import re

_TIMESPAN = re.compile(r"^\d{1,4}[smhd]$")          # 30s, 15m, 1h, 7d


class ADXBackend:
    def __init__(self):
        from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
        cluster = os.environ["ADX_CLUSTER_URI"]     # https://<name>.<region>.kusto.windows.net
        self.database = os.environ.get("ADX_DATABASE", "watchdog")
        client_id = os.environ.get("ADX_MANAGED_IDENTITY_CLIENT_ID")
        if client_id:                               # user-assigned managed identity
            kcsb = KustoConnectionStringBuilder.with_aad_managed_service_identity_authentication(cluster, client_id=client_id)
        elif os.environ.get("ADX_USE_AZ_CLI") == "1":  # local development
            kcsb = KustoConnectionStringBuilder.with_az_cli_authentication(cluster)
        else:                                       # system-assigned managed identity
            kcsb = KustoConnectionStringBuilder.with_aad_managed_service_identity_authentication(cluster)
        self.client = KustoClient(kcsb)

    def run(self, function_name: str, params: dict) -> list:
        args = []
        for k, v in params.items():
            if not _TIMESPAN.match(str(v)):
                raise ValueError(f"{k} must look like 15m / 1h / 7d")
            args.append(f"timespan({v})")
        query = f"{function_name}({', '.join(args)})"
        resp = self.client.execute(self.database, query)
        table = resp.primary_results[0]
        cols = [c.column_name for c in table.columns]
        return [{c: _json_safe(row[c]) for c in cols} for row in table]


def _json_safe(v):
    if hasattr(v, "isoformat"):
        return v.isoformat()
    # Empty aggregates arrive as NaN (a float, or the string "NaN"); NaN is not valid JSON.
    if (isinstance(v, float) and not math.isfinite(v)) or v in ("NaN", "Infinity", "-Infinity"):
        return None
    return v
