# 02 — System Architecture

## 2.1 The layering rule

Everything in this architecture follows from one rule, learned by dropping a robot on a floor:

> **Safety enforcement lives in the driver, adjacent to the state machine that knows which
> transitions are legal. Nothing above the driver may bypass it.**

The predecessor system violated this. A vision dashboard on a separate machine held the
robot's velocity limits and ran a deadman watchdog that POSTed `/stop` every 200 ms. That stop
path internally sent `BalanceStand` before `Move(0,0,0)`, and `BalanceStand` sent to an
already-standing Go2 is a firmware safety fault. A single D-pad press therefore armed a loop
that would eventually fell a standing robot. The remote watchdog could not have known this;
the knowledge lived in firmware three network hops away.

Anthropic's Model Hardware Standard reached the same architecture independently. Per QuEra,
one of its launch partners, MHS enforces limits "at the hardware interface, independent of the
model," and Anthropic's own framing is that safety checks fire *before* motion.

## 2.2 Layer diagram

```
┌───────────────────────────────────────────────────────────────────────┐
│  BROWSER                                                              │
│  React · three.js/R3F 3D editor · live mission monitor · fleet view   │
└───────────────────────────────┬───────────────────────────────────────┘
                                │ HTTPS + WebSocket
┌───────────────────────────────▼───────────────────────────────────────┐
│  CONTROL PLANE            (cloud or on-prem server)                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐   │
│  │ Mission  │ │   Map    │ │  Robot   │ │  Action  │ │  Capture   │   │
│  │  Store   │ │  Store   │ │ Registry │ │ Registry │ │   Index    │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └────────────┘   │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │ Validator · Deployer · Telemetry Ingest · MCP/MHS Gateway      │   │
│  └────────────────────────────────────────────────────────────────┘   │
└───────────────────────────────┬───────────────────────────────────────┘
                                │ MQTT (VDA 5050 topics) + HTTPS bulk
        ═══════════════════════ NETWORK BOUNDARY ═══════════════════════
                                │  ← everything below survives disconnect
┌───────────────────────────────▼───────────────────────────────────────┐
│  EDGE RUNTIME             (on-robot compute — Jetson Orin)            │
│  ┌────────────────────────────────────────────────────────────────┐   │
│  │ Mission Executor — owns the run; sequences waypoints/actions   │   │
│  └───────────────┬──────────────────────────┬─────────────────────┘   │
│                  │                          │                         │
│  ┌───────────────▼──────────┐  ┌────────────▼──────────────────────┐  │
│  │ Action Runtime           │  │ Navigation                        │  │
│  │ (plugin sandbox, tick)   │  │ (localization, planner, geofence) │  │
│  └───────────────┬──────────┘  └────────────┬──────────────────────┘  │
│                  │                          │                         │
│  ┌───────────────▼──────────────────────────▼─────────────────────┐   │
│  │ SAFETY SUPERVISOR   ← every motion command passes through here │   │
│  │ posture state machine · limit enforcement · deadman · e-stop   │   │
│  └───────────────────────────┬────────────────────────────────────┘   │
│  ┌───────────────────────────▼────────────────────────────────────┐   │
│  │ ROBOT DRIVER  (vendor-specific; Go2 = WebRTC datachannel)      │   │
│  └───────────────────────────┬────────────────────────────────────┘   │
│  ┌──────────────┐ ┌──────────▼─────────┐ ┌──────────────────────┐     │
│  │ Sensor Hub   │ │ State Store        │ │ Capture Store        │     │
│  │ (frame bus)  │ │ (shared memory)    │ │ (MCAP + sync queue)  │     │
│  └──────────────┘ └────────────────────┘ └──────────────────────┘     │
└───────────────────────────────┬───────────────────────────────────────┘
                                │ vendor protocol
┌───────────────────────────────▼───────────────────────────────────────┐
│  ROBOT      Unitree Go2 · G1 · AMR                                    │
└───────────────────────────────────────────────────────────────────────┘
```

## 2.3 The network boundary is the most important line

**A mission must execute to completion with the control plane unreachable.** The control plane
authors, validates, distributes, and archives. It is never in the execution loop.

This is not merely a resilience nicety. The network is precisely what fails in the scenario a
geofence exists to handle. A geofence enforced in the cloud is not a geofence.

Concretely, everything below the boundary must work offline:

- Mission execution, including all navigation and action running.
- Geofence enforcement.
- E-stop, deadman, and every safety response.
- Data capture and on-robot storage.

The control plane's loss degrades the system to: no live monitoring, no new deployments, no
cloud sync. The robot finishes its patrol.

## 2.4 Control plane components

| Component | Responsibility |
|---|---|
| **Mission Store** | Versioned mission definitions. Immutable once deployed; edits create versions. |
| **Map Store** | Point clouds, occupancy grids, pose graphs, zone sets. Content-addressed, versioned. Serves COPC tiles by HTTP range request. |
| **Robot Registry** | Known robots, their archetype, address, credentials, last-known state. The only place an endpoint is resolved — no IP literal exists anywhere else in the system. |
| **Action Registry** | Aggregated capability descriptors. Answers "which actions can archetype X perform, with what parameters." |
| **Capture Index** | Metadata index over captures. Points at object storage; never stores blobs itself. |
| **Validator** | Static mission validation. Pure function: `(mission, map, zoneSet, factsheet) → Result[]`. |
| **Deployer** | Pushes a mission bundle to an edge runtime, verifies receipt and integrity. |
| **Telemetry Ingest** | Consumes VDA 5050 `state`/`visualization`, writes to time-series storage, fans out to live UI sockets. |
| **MCP/MHS Gateway** | Exposes the platform to AI agents. See [03_CONTRACTS.md](03_CONTRACTS.md) §3.9. |

**Technology recommendation.** Python + FastAPI for the control plane; it matches the team's
existing stack and the robotics ecosystem is Python-native. PostgreSQL with PostGIS for
missions, maps metadata, and zone geometry. S3-compatible object storage for blobs. MQTT
broker (EMQX or Mosquitto) for VDA 5050 topics. TypeScript + Next.js for the frontend.

## 2.5 Edge runtime components

The edge runtime is a set of cooperating processes on the robot's onboard compute — a Jetson
Orin in the reference hardware.

**Process isolation matters here, and the reason is specific.** The predecessor system ran
robot control, video encoding, and an HTTP API in one 777-line file with no interface
boundaries, and its README carries this warning:

> *"Do not add watchdog logic, automatic restarts, or complex error recovery to this service.
> Those features caused the service to fail."*

Read carefully, that is not an argument against reliability engineering. It is an argument
that **recovery logic must not live inside the process that owns the robot connection**,
because a WebRTC session cannot survive the event-loop disruption that restart logic
introduces. The fix is a supervisor process, which is what this architecture provides.

| Process | Responsibility | Restart policy |
|---|---|---|
| **Supervisor** | Starts, monitors, and restarts every other process. Owns nothing itself. | systemd, always |
| **Robot Driver** | Owns the vendor connection. One asyncio loop, one thread. No restart logic inside. | Supervisor restarts it |
| **Safety Supervisor** | Enforces limits, owns posture state machine, deadman, e-stop. | Never auto-restarts — failure here stops the robot |
| **Mission Executor** | Sequences the mission. Stateless across restarts by checkpointing progress. | Supervisor restarts, resumes from checkpoint |
| **Action Runtime** | Hosts plugin processes. One subprocess per action invocation. | Per-invocation |
| **Sensor Hub** | Owns cameras and lidar. Publishes to the frame bus. **Demand-driven.** | Supervisor restarts |
| **Navigation** | Localization, planning, geofence enforcement. | Supervisor restarts |
| **Sync Agent** | Uploads captures to object storage. Store-and-forward. | Supervisor restarts |

> **Sensor Hub must be demand-driven — this is a hard requirement, not a preference.** The
> predecessor's RealSense RTSP server consumed **103% CPU with zero clients connected**,
> pushing a 4-core Orin to a load of 3.88 and making camera switches take 30+ seconds. The
> cause was a frame-pump timer and a `while True: poll_for_frames()` producer that ran
> regardless of whether anyone was watching. Two attempted fixes failed. Sensors must start
> on first subscriber and stop on last.

## 2.6 The state store and MHS alignment

Continuous telemetry — pose, battery, IMU, video frames, point clouds — lives in a
**shared-memory state dictionary** on the edge runtime that any local process can attach to
and read concurrently.

This design is chosen deliberately to align with MHS, whose one confirmed streaming mechanism
is exactly this: "Each data stream is stored in shared memory in the MHS state dictionary, in
a documented format that is readable by any process that attaches to it."

It also fixes a concrete predecessor defect. That system had **no frame queue anywhere** — a
single `current_frame` slot under a lock, with a full image copy per consumer read. That is
workable for one live viewer and unusable for recording, replay, or multi-consumer fan-out,
all of which this platform requires.

**Implementation:** POSIX shared memory via Python's `multiprocessing.shared_memory`, with a
small ring buffer per stream and a lock-free sequence-number protocol so readers detect torn
reads. Frame payloads are zero-copy; metadata is a versioned struct.

**Rates and directionality.** The state store is *read* by many and *written* by one owner per
key. Ownership is declared at startup and never transferred at runtime.

## 2.7 Deployment topology

The reference deployment has three tiers. The architecture does not assume this shape, but the
Go2 driver's constraints make it the practical arrangement.

| Tier | Reference hardware | Runs |
|---|---|---|
| **Control plane** | Cloud VM or on-prem server | All control plane components |
| **Edge compute** | Jetson Orin NX 16 GB, on the robot | Entire edge runtime |
| **Robot** | Unitree Go2 | Firmware only |

**Why edge compute rides on the robot.** The Go2's control board is reachable over an internal
wired subnet (`192.168.123.x`) from a backpack computer over RJ45, but only over WiFi from
anywhere else. WiFi introduces 4–97 ms jitter (σ ≈ 40 ms measured). A safety supervisor cannot
sit behind that link. Putting the edge runtime on the robot's own back makes the
safety-critical path a wired connection with no contention.

**A second reason:** the mission must survive network loss, and a mission executor on the far
side of a WiFi link does not.

### GPU contention on shared edge compute

The Orin runs navigation, perception, and possibly SLAM concurrently. The predecessor system
had no GPU coordination at all — frame skipping was the entire budget mechanism, producing 3.8
detection FPS, and a field incident suggested one model's GPU use could corrupt another's CUDA
context.

**Rule: one process owns the GPU context per accelerator.** Models needing GPU inference run
inside that process and are multiplexed by an explicit queue with declared priorities. This
sidesteps the context question entirely rather than debugging it.

Priority order during mission execution: **localization > obstacle detection > mission actions
> narration.** Anything below localization is droppable under load, and dropping must be
recorded, never silent.

## 2.8 Transport and protocol choices

| Path | Protocol | Rationale |
|---|---|---|
| Browser ↔ control plane | HTTPS + WebSocket | Standard. WebSocket for live telemetry fan-out. |
| Control plane ↔ edge | **MQTT**, VDA 5050 topic structure | The standard's own transport. Topics: `omnicontrol/v3/<manufacturer>/<serial>/{order,instantActions,state,visualization,connection,factsheet,zoneSet,responses}`. QoS 1, retained `connection` messages with LWT for offline detection. |
| Map / capture bulk transfer | HTTPS, range requests | Large blobs must not traverse MQTT. COPC point clouds stream by range request. |
| Teleop control | **WebRTC DataChannel, unreliable + unordered** | A stale control command is worse than no command. TCP head-of-line blocking adds 10–50 ms on loss. |
| Teleop video | WebRTC media | Already the Go2's native transport. |
| Edge internal | Shared memory + Unix domain sockets | No network stack in the safety path. |

> **Do not put a safety-relevant heartbeat on a WebSocket or a Foxglove bridge.** Both are
> designed around reliable, ordered delivery, and their behavior on lossy links is
> unspecified. The deadman heartbeat is WebRTC DataChannel or nothing.

## 2.9 What runs where — the abstraction seams

Thirteen specific places where the predecessor system fused Go2 knowledge into general code
are catalogued in [06_GO2_DRIVER_REFERENCE.md](06_GO2_DRIVER_REFERENCE.md) §E.10. The
architecture answers each:

| Predecessor leak | Architectural answer |
|---|---|
| Perception called the actuator directly | Perception publishes typed events; a policy layer maps events to capabilities |
| Robot velocity limits lived in the vision web app | Declared in the capability descriptor, enforced by the Safety Supervisor |
| Posture state machine used string comparison in nine places | Declarative transition table per archetype, one owner |
| Command vocabulary was a 4-entry dict of vendor integers | Capability registry of semantic verbs; driver owns the mapping |
| VLM prompts hardcoded robot species and camera height | Persona templated from the capability descriptor |
| Gesture geometry assumed a 12-inch camera | Camera extrinsics are explicit descriptor parameters |
| Camera sources were an enum of vendor strings | URI-addressed sensor providers |
| `robot_id` was a hardcoded literal; every component a singleton | Instance-scoped components keyed by robot ID |
| Endpoints hardcoded despite config existing for them | Robot Registry is the only endpoint resolver |
| Five different reconnect policies, two paths with none | One reconnect policy object |
| No frame queue anywhere | Shared-memory frame bus with multi-consumer fan-out |
| A display setting silently armed a physical action | Arming is explicit and separate from display state |
| Lidar, odometry, SLAM, audio, arm all unmodeled | Full sensor surface modeled in the descriptor; v1 implements a subset |

## 2.10 Failure domains

| Domain | Blast radius | Mitigation |
|---|---|---|
| Control plane down | No authoring, no monitoring, no sync | Missions execute; captures queue locally |
| Network partition | Same as above | Sync Agent store-and-forward; MQTT LWT marks robot offline |
| Edge compute crash | Robot stops | Supervisor restarts; safety supervisor failure triggers Cat 2 stop |
| Driver crash | Robot loses commands | Watchdog in Safety Supervisor triggers Cat 2 stop, then Cat 1 after timeout |
| Robot firmware fault | Robot may fall | Driver posture heartbeat prevents the known case; see Go2 §E.5 |
| Action plugin crash / hang | One action fails | Subprocess isolation, hard timeout, mission failure policy decides |
| GPU exhaustion | Degraded perception | Priority queue drops low-priority inference, records the drop |
| Storage full | Captures lost | Sync Agent reserves headroom; capture failures surface as mission warnings |
