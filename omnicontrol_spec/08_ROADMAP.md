# 08 — Roadmap, Decisions & Open Questions

## 8.1 Phase 0 — Validate the assumptions (do this first)

**This specification contains assumptions that must be tested against real hardware before
significant code is written.** Phase 0 exists so that validation is the first work item rather
than a discovery made in month three.

| # | Question | How to answer | Blocks |
|---|---|---|---|
| **0.1** | Are the Go2's `rt/uslam/*` SLAM topics populated on stock firmware? At what rate, in which frame? | Subscribe and log. Nobody on the predecessor project ever did. | Entire mapping strategy |
| **0.2** | Is the Go2's native lidar adequate for mapping, or is a Livox Mid-360 required? | Build a map with each. | Hardware BOM |
| **0.3** | What is the real-time factor of the chosen SLAM stack on the target Orin, alongside perception? | Benchmark. **No published Orin numbers exist for any candidate.** | Compute sizing |
| **0.4** | Is `power_v` millivolts or volts? | Read it, compare to a multimeter. | Battery safety gates |
| **0.5** | Does the sport-heartbeat + posture state machine actually hold a Go2 standing indefinitely? | Run it for four hours. | Safety supervisor |
| **0.6** | Can MHS research-preview access be obtained? | Apply at the form. | MHS adapter scope |

> **0.1 is the highest-value question in the entire project.** If the firmware's own SLAM
> topics are usable, mapping becomes a subscription instead of a compute-hungry pipeline
> running alongside perception on a shared Orin. The presence of `rt/lio_sam_ros2/mapping/odometry`
> suggests the firmware runs a LIO-SAM derivative internally. Nobody has checked.

Also retrieve **`rtsp_rs.py` from the Orin's filesystem** — it is the predecessor's worst
performance bottleneck (103% CPU at idle) and it exists in no repository.

## 8.2 Build sequence

Each phase ends with something demonstrable. Phases 1–3 deliberately deliver no autonomy —
they establish the contracts that make autonomy safe.

### Phase 1 — Driver and safety foundation

Capability descriptor schema and loader. Go2 driver implementing `read`/`write`. **Safety
Supervisor with the posture state machine and limit enforcement.** Two-tier heartbeat with
challenge/response. Supervisor process management. Shared-memory state store.

*Demonstrable:* the robot can be commanded from a CLI, refuses illegal transitions with
readable reasons, holds a stand indefinitely, and stops on heartbeat loss.

*This phase is where the predecessor's hardest-won knowledge gets encoded. Do not compress it.*

### Phase 2 — Sensors and teleoperation

Demand-driven Sensor Hub with the multi-consumer frame bus. WebRTC teleop with deadman. Web
shell, design system, fleet and robot-detail screens. Live telemetry over VDA 5050 `state`.

*Demonstrable:* drive the robot from a browser with correct deadman and latency behavior.

### Phase 3 — Mapping

SLAM integration (per Phase 0 findings). Mapping session UI with live cloud streaming. Map
store, versioning, extrinsics hash. COPC conversion pipeline. Relocalization with operator
confirmation.

*Demonstrable:* drive the robot around a floor, produce a saved map, reload and relocalize.

### Phase 4 — Mission authoring

3D mission editor: placement, heading, reorder, the full triad. Action plugin system with
schema-generated forms. Zone-set editor. Static validator.

*Demonstrable:* author a complete patrol and see it validate.

### Phase 5 — Execution

Mission Executor with VDA 5050 order semantics. Action Runtime with subprocess isolation.
Deployer. Preflight. Live run screen. Capture store, MCAP recording, S3 sync.

*Demonstrable:* **the whole loop.** Author, deploy, execute, review.

### Phase 6 — Agent interface and second robot

MCP server. MHS adapter if access was granted. **Onboard a second archetype — the real test of
the abstraction.**

> **Phase 6's second robot is the acceptance test for this entire specification.** If adding a
> G1 requires changes anywhere outside `drivers/` and a capability descriptor, the abstraction
> failed and should be fixed before more features land on top of it.

## 8.3 Decisions already made

| Decision | Rationale |
|---|---|
| VDA 5050 v3.0 as the mission model | De-AGV-ified in March 2026 for exactly this case; solves ordering, partial release, blocking, action lifecycle |
| VDA 5050 `factsheet` as the capability descriptor | The only real, shipping, industrially-adopted robot capability format |
| REP-103 / REP-105 verbatim | Free interoperability with every ROS tool, Foxglove, and Rerun |
| MCAP for on-robot recording | Attachments, metadata records, indexed seeking; the Run hierarchy as one file |
| COPC for browser point clouds | Single file, HTTP range streamable, no Potree conversion pipeline |
| Safety enforced in the driver | The core architectural lesson; independently confirmed by MHS |
| Cat 1 settle-then-cut as e-stop default | Cat 0 makes a quadruped fall, which ISO 13850 forbids |
| Heading defaults to auto | Highest-leverage ease-of-use decision available |
| Actions are reusable library entities | Makes longitudinal asset comparison possible; retrofitting is painful |
| Tick-based plugin protocol | The only shape that survives pause and resume |
| Design against MHS semantics, not schemas | No MHS schema is published; guessing field names would be a category error |

### Rejected, with reasons

| Rejected | Why |
|---|---|
| **MassRobotics AMR Interop** | Last commit 2021-10-08. Monitoring only — no order, node, edge, or action model. The promised v2.0 never shipped. |
| **Nav2 `WaypointTaskExecutor`** | One plugin per node, boolean return, no per-waypoint parameters. Cannot carry a measurement. |
| **Potree** | Only major point-cloud library that has gone quiet; unclear license classification. Use COPC + three.js. |
| **KSP-style heading gizmo** | Canonically unlearnable; its own community built a mod to add numeric entry. |
| **Cloud-side geofence enforcement** | The network is what fails in the scenario the geofence exists for. |
| **Restart logic inside the robot driver** | Directly caused the predecessor's `cannot reuse already awaited coroutine` failure. |
| **VDA 5050 v2.x** | AGV-specific field names; superseded. |

## 8.4 Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Go2 firmware SLAM topics unusable | High | Phase 0.1 answers it before commitment |
| Orin cannot run SLAM + perception + navigation | High | Phase 0.3 benchmarks; fall back to reduced perception during mapping |
| VDA 5050 v3 has little field adoption | Medium | We control both ends; adoption matters only for third-party integration |
| MHS never opens, or opens incompatibly | Low | Adapter is isolated; platform ships without it |
| Legged safety standards unresolved | Medium | Document limitations honestly; track ISO/CD 25785-1 |
| ZeroTier-style VPN instability at remote sites | Medium | Already observed in the field; the offline-execution architecture makes it a monitoring problem, not a mission problem |
| Point-cloud rendering performance in browser | Medium | COPC LOD streaming; cap rendered points; benchmark early |

## 8.5 Open questions — everything unverified, in one place

### Standards

- **VDA 5050 `maxRotationSpeed` vs `maximumRotationSpeed`** — the JSON schema and the spec
  prose disagree. The repository README says the VDA PDF is authoritative. **Check the PDF.**
- **VDA 5050 `grantType` vs `responseType`** — same situation, in the `responses` message.
- Real-world v3.0 adoption is unknown; 2.1.0 is probably what integration partners speak today.

### MHS

- Reference file format, field names, transport, discovery, auth, rate limiting, e-stop
  protocol, versioning, and license are **all unpublished**.
- Whether MHS has a "device server" analogous to an MCP server is genuinely ambiguous in
  Anthropic's own text — the driver plus shared-memory framing suggests an in-process library,
  but "across networks" implies a network component.
- **Whether MHS has a stable machine schema at all**, given the reference file is auto-generated
  from natural-language tags.

### Go2 platform

- Native lidar coordinate frame, publish rate, and extrinsics — **all undocumented and never
  measured** on this project.
- `power_v` units (millivolts vs volts) — the predecessor's own code and docs disagree.
- Whether `rt/uslam/*` and `rt/sportmodestate` are populated on stock firmware.
- Go2 L1 lidar effective point rate is roughly 21,600 points/s — about a tenth of a Livox
  Mid-360. Multiple published projects report distorted maps using it alone.

### SLAM

- **No published real-time-factor, CPU, GPU, or memory figures exist for any candidate stack on
  a Jetson Orin.** This is the largest technical gap in the research and must be benchmarked.
- **No published head-to-head LIO benchmark on a Unitree Go2 exists.** The nearest legged
  evaluation is on ANYmal-D, which has a tactical-grade IMU — a materially easier problem than
  the Go2's cheap MEMS IMU and snappier gait.
- Licensing matters commercially: FAST-LIO2, Faster-LIO, and Point-LIO are GPL-2.0. MIT/BSD
  alternatives include RKO-LIO, GLIM, KISS-ICP, DLIO, Leg-KILO, and small_gicp. **Check before
  shipping.** Note also that `untwine`, in some point-cloud pipelines, is GPL-3.0.
- GLIM reportedly degrades above 20 Hz point-cloud rate — keep lidar at 10 Hz.

### Safety

- ISO 3691-4:2023 numeric limits are paywalled and unread.
- ANSI/A3 R15.08-3 (user requirements) publication status needs confirmation with A3.
- ISO/CD 25785-1 stage read from secondary sources only.
- **The protective-field problem on a pitching, rolling, height-changing legged body is
  unresolved industry-wide.** This spec does not solve it.

### Commercial prior art

- Boston Dynamics Orbit's full REST schema, webhook payload format, and the `.walk` file format
  were not verified.
- ANYbotics and Ghost Robotics publish no developer documentation; their field-level data
  models are unknown.
- Fleet-ops vendor claims (Formant, InOrbit, Freedom) came from low-quality sources. **Do not
  quote pricing.**

## 8.6 What success looks like

**Phase 5:** an operator who has never used the platform walks up, selects a Go2, loads a map,
adds an inspection point with a photo action, deploys, and watches it run — in under five
minutes, without assistance.

**Phase 6:** a second robot archetype is onboarded by writing a driver and a capability
descriptor, with **zero changes to the platform.**

If both hold, the architecture is correct.
