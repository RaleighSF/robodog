"""Event Hubs -> ADX ingest (ADR 0008).

Stands in for the ADX Event Hubs data connection, which the free cluster only
offers through its web UI. Each trigger batch is streamed into RawEvents with
RawEventsMapping, so the update policies in setup.kql fill the typed tables
exactly as the data connection would. Event Hubs is at-least-once: a restart
can replay a batch, so rare duplicate rows are possible."""
import gzip
import io
import json
import logging
from typing import List

import azure.functions as func

bp = func.Blueprint()
_client = None


def _kusto():
    global _client
    if _client is None:
        from backends.adx import ADXBackend      # same identity rules as the read routes
        _client = ADXBackend()
    return _client


@bp.retry(strategy="exponential_backoff", max_retry_count="5",
          minimum_interval="00:00:02", maximum_interval="00:01:00")
@bp.event_hub_message_trigger(arg_name="events", connection="TELEMETRY_EVENTHUB",
                              event_hub_name="%TELEMETRY_EVENTHUB_NAME%",
                              consumer_group="$Default", cardinality=func.Cardinality.MANY)
def telemetry_ingest(events: List[func.EventHubEvent]):
    from azure.kusto.data.data_format import DataFormat

    lines = []
    for e in events:
        body = e.get_body().strip()
        try:
            json.loads(body)                     # one malformed event must not sink the batch
        except ValueError:
            logging.warning("skipping non-JSON event (%d bytes)", len(body))
            continue
        lines.append(body)
    if not lines:
        return
    # The SDK always sends Content-Encoding: gzip, so the body must be gzipped.
    data = gzip.compress(b"\n".join(lines) + b"\n")
    k = _kusto()
    k.client.execute_streaming_ingest(k.database, "RawEvents", io.BytesIO(data), None, DataFormat.MULTIJSON,
                                      mapping_name="RawEventsMapping")
    logging.info("ingested %d events", len(lines))
