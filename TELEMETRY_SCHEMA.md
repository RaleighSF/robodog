# Watch Dog Telemetry Schema — Integration Guide

**Bucket:** `s3://watchdog-telemetry` (us-east-1, account 251197268325)
**Schema version:** `1.0.0`
**Active deployment:** `watchdog-snowflake-summit-2026`

---

## S3 Key Layout

All data lives under the `v1/` prefix with Hive-style partitioning:

```
v1/events/year=2026/month=05/day=12/hour=17/evt_<timestamp>_<id>.json
v1/images/year=2026/month=05/day=12/hour=17/<event_id>.jpg
v1/thumbnails/year=2026/month=05/day=12/hour=17/<event_id>.jpg
```

Partition columns (`year`, `month`, `day`, `hour`) are UTC. Each event is a single JSON file (~1 KB for heartbeats, ~2-3 KB for detections). Images are separate JPEG files referenced by key in the JSON payload.

## Publish Cadence

| Event Type | Frequency | Description |
|---|---|---|
| `heartbeat` | Every **30 seconds** | System health, battery, vision config snapshot |
| `detection` | **Per detection frame** (~4 FPS when active) | Object detections with bounding boxes and confidence scores |
| `command` | **On demand** | Robot commands (stand, crouch, sit, shake) with success/failure |
| `alert:*` | **On trigger** | Battery low, stream loss, connection changes |

Expect ~120 heartbeat events/hour at baseline. Detection events scale with camera activity — up to ~14,400/hour at full detection rate.

## Event Schema

Every event shares this top-level envelope:

```json
{
  "schema_version": "1.0.0",
  "event_id": "evt_20260512T173645Z_6eb16790",
  "event_type": "heartbeat | detection | command | alert:<subtype>",
  "deployment_id": "watchdog-snowflake-summit-2026",
  "session_id": "sess_20260512T173614Z_2dd6a3",
  "timestamp": "2026-05-12T17:36:45.695Z",
  "device": { ... },
  "robot": { ... },
  "vision": { ... },
  "system_health": { ... }
}
```

### `device` — Edge compute node identity

| Field | Type | Example | Notes |
|---|---|---|---|
| `device_id` | string | `"watchdog-edge-01"` | Stable across reboots |
| `device_type` | string | `"nvidia_agx_xavier"` | Hardware platform |
| `hostname` | string | `"ubuntu"` | OS hostname |
| `platform` | string | `"linux-aarch64"` | OS + architecture |

### `robot` — GO2 quadruped state

| Field | Type | Example | Notes |
|---|---|---|---|
| `robot_id` | string | `"go2-unit-01"` | Robot identifier |
| `battery.soc` | float | `99` | State of charge (0-100%) |
| `battery.voltage` | float | `31.686502` | Pack voltage in volts |
| `battery.current` | float | `-18` | Current in mA (negative = charging) |
| `battery.connected` | bool | `true` | WebRTC connection to robot alive |
| `motion_mode` | string | `"normal"` | Current motion controller mode |
| `last_command` | object\|null | `{"command":"stand","success":true,...}` | Most recent command (on command events) |

### `last_command` (when present)

| Field | Type | Example |
|---|---|---|
| `command` | string | `"stand"` |
| `issued_at` | string | `"2026-05-12T17:40:00.000Z"` |
| `success` | bool | `true` |
| `message` | string | `""` |

### `vision` — Detection pipeline state

| Field | Type | Example | Notes |
|---|---|---|---|
| `detection_mode` | string | `"text"` | `text`, `visual`, `nlp`, or `open` |
| `detector` | string | `"yoloe"` | Model family |
| `model` | string | `"yolo11s.pt"` | Model weights file |
| `confidence_threshold` | float | `0.25` | Min confidence for detections |
| `iou_threshold` | float | `0.45` | NMS overlap threshold |
| `classes_configured` | array | `["ball"]` | Target classes for text mode |
| `frame.width` | int | `1920` | Source frame width in pixels |
| `frame.height` | int | `1080` | Source frame height in pixels |
| `frame.source_type` | string | `"rtsp"` | Camera source type |
| `detections` | array | `[...]` | List of detection entries (below) |
| `detection_count` | int | `3` | Number of objects detected |
| `detection_image_key` | string\|null | `"images/year=.../evt_xxx.jpg"` | S3 key for full frame JPEG (960px max) |
| `thumbnail_image_key` | string\|null | `"thumbnails/year=.../evt_xxx.jpg"` | S3 key for thumbnail JPEG (320px max) |

### `detections[]` — Individual object detections

| Field | Type | Example | Notes |
|---|---|---|---|
| `class_name` | string | `"ball"` | Detected object class |
| `class_id` | int | `0` | Numeric class index |
| `confidence` | float | `0.8742` | Detection confidence (0-1) |
| `bbox.x` | int | `412` | Bounding box top-left X (pixels) |
| `bbox.y` | int | `238` | Bounding box top-left Y (pixels) |
| `bbox.w` | int | `85` | Bounding box width (pixels) |
| `bbox.h` | int | `91` | Bounding box height (pixels) |

### `system_health` — Edge compute metrics

| Field | Type | Example | Notes |
|---|---|---|---|
| `uptime_seconds` | float | `30.8` | Time since telemetry started |
| `stream_active` | bool | `false` | Video stream being served |
| `detection_worker_alive` | bool | `true` | Detection thread running |
| `detection_fps` | float | `3.8` | Current detection throughput |
| `frames_processed` | int | `1542` | Total frames analyzed |
| `go2_service_reachable` | bool | `true` | Orin backpack HTTP accessible |
| `rtsp_server_running` | bool\|null | `true` | RTSP camera service on Orin |

## Snowflake Integration

### External Stage

```sql
CREATE OR REPLACE STAGE watchdog_telemetry_stage
  URL = 's3://watchdog-telemetry/v1/events/'
  CREDENTIALS = (AWS_KEY_ID = '...' AWS_SECRET_KEY = '...')
  FILE_FORMAT = (TYPE = JSON);
```

### Querying Raw Events

```sql
SELECT
  $1:event_id::STRING AS event_id,
  $1:event_type::STRING AS event_type,
  $1:timestamp::TIMESTAMP_NTZ AS event_ts,
  $1:robot.battery.soc::FLOAT AS battery_pct,
  $1:robot.battery.voltage::FLOAT AS voltage,
  $1:robot.battery.connected::BOOLEAN AS robot_connected,
  $1:vision.detection_count::INT AS detections,
  $1:system_health.uptime_seconds::FLOAT AS uptime_s
FROM @watchdog_telemetry_stage
WHERE $1:event_type = 'heartbeat'
ORDER BY event_ts DESC
LIMIT 100;
```

### Flattening Detections

```sql
SELECT
  $1:event_id::STRING AS event_id,
  $1:timestamp::TIMESTAMP_NTZ AS event_ts,
  d.value:class_name::STRING AS object_class,
  d.value:confidence::FLOAT AS confidence,
  d.value:bbox.x::INT AS bbox_x,
  d.value:bbox.y::INT AS bbox_y,
  d.value:bbox.w::INT AS bbox_w,
  d.value:bbox.h::INT AS bbox_h,
  $1:vision.detection_image_key::STRING AS image_key
FROM @watchdog_telemetry_stage,
  LATERAL FLATTEN(input => $1:vision.detections) d
WHERE $1:event_type = 'detection'
ORDER BY event_ts DESC;
```

## Schema Versioning

- `schema_version` follows semver: `MAJOR.MINOR.PATCH`
- **Minor bumps** (1.1.0): new fields added — always additive, never breaking
- **Major bumps** (2.0.0): field removals, type changes, or structural changes — new `v2/` prefix in S3
- Consumers should tolerate unknown fields gracefully

## Live Monitoring

Dashboard stats endpoint: `GET http://<agx-ip>:8000/api/telemetry/stats`

```json
{
  "enabled": true,
  "deployment_id": "watchdog-snowflake-summit-2026",
  "session_id": "sess_...",
  "events_emitted": 120,
  "events_uploaded": 120,
  "events_failed": 0,
  "buffer_size": 0,
  "image_queue_size": 0,
  "uptime_seconds": 3600.0
}
```
