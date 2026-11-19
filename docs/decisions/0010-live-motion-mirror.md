# 0010 Live motion mirror and maneuver recognition
Date: 2026-10-30 · Status: Accepted (user chose option A: managed real-time channel)

## Context
The 3D dog followed joint angles from the 5 s vitals, too slow to show a shake
(about 2 s). Three options were considered:
- A: managed WebSocket fan-out.
- B: replay through Event Hubs → ADX, which lags 3–6 s.
- C: a direct WebSocket to the Thor, which bypasses the cloud and needs a trusted cert.

The dog does not report which remote or app trick it is doing (`mode` reads 0),
so maneuvers must be recognized from the motion itself.

## Decision
- **Orin.** A read-only `/joints` SSE stream: 12 joint angles + rpy + body height,
  at 20 Hz.
- **Thor.** `motion_stream.py` reads the stream and publishes 5 batches/s to Azure
  Web PubSub (Standard_S1, hub/group `motion`) with a send-to-group-only token,
  valid about 90 days and stored at `/state/motion.token`.
  - It recognizes hello (with paw side), sit, stand_up and lie_down, each grounded
    in captured data.
  - Recognized maneuvers go out as schema-1.2 `maneuver` telemetry, landing in the
    ADX `Maneuvers` table, the `maneuvers_recent` op and an advisory finding.
- **Query API.** `GET motion/negotiate` returns a shared receive-only client URL,
  valid 60 min and minted with the Function's managed identity. Local auth (access
  keys) is disabled on the Web PubSub.
- **Dashboard.** A jitter-buffered mirror renders 250 ms behind, falls back to the
  vitals pose when the stream stops, and shows a maneuver badge.

## Consequences
- **Measured:** about 15 frames/s and a median lag of about 64 ms from the Orin to a
  subscriber. The lag figure relies on the Orin's clock.
- **Cost:** a Standard unit costs about $1.61 per unit per day. This is a
  third-party figure that is not confirmed on Microsoft's page. Delete the unit, or
  scale to Free, between shows.
- **Rotation:** the Thor token must be re-minted before 2027-01-28. Mint it with
  `:generateToken` using `role=webpubsub.sendToGroup.motion`.
- **Untested maneuvers:** stretch, dance and jump each need a capture before
  they get a rule.

## AWS parity
- API Gateway WebSocket API or AWS IoT Core (MQTT over WSS) carries the same batch
  JSON.
- A Lambda behind the same `motion/negotiate` contract returns `{url, protocol}`.
- The edge publisher gets an IoT policy, or an IAM role scoped to publish-only on
  one topic.
- `Maneuvers` becomes an Athena view with the same columns.
