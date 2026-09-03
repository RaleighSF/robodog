# 07 — Safety Model

> **Read this before writing any code that moves a robot.**
>
> This document is engineering guidance, not legal or compliance advice. Standards conformance
> for a deployed robot requires a qualified safety assessor. Where a standard is cited, the
> edition was checked in September 2026, but paywalled numeric limits were not read and are
> marked as such.

## 7.1 The honest statement, up front

**Nothing in this software stack is safety-rated, and nothing in it can be.**

A stop function claimed at ISO 13849-1 Performance Level d requires dual-channel,
cross-monitored hardware with ≥90% diagnostic coverage, where a single fault cannot defeat the
stop. Nothing running in Python, on a Jetson, or across a WiFi link can make that claim. This
is not a limitation to engineer around — it is a categorical boundary.

Consequences that must hold throughout the product:

1. **The UI's stop control is a *protective stop*, not an *emergency stop*.** ISO 13850
   requires a hardware-latched circuit with direct-opening action and manual reset, independent
   of software. Label the software control accordingly, and state in the documentation that
   the physical e-stop is the safety device. Mislabeling it creates real liability and, worse,
   false operator confidence.
2. **Publish residual risks and require the deploying organization to complete its own risk
   assessment.** This is Boston Dynamics' posture for Spot and it is the correct one.
3. **Do not claim conformance to any standard** in marketing or documentation without an
   assessor's sign-off.

## 7.2 The architectural rule

> **Safety enforcement lives in the driver, adjacent to the state machine that knows which
> transitions are legal. Nothing above the driver may bypass it.**

The predecessor system placed a robot's velocity limits and its deadman watchdog in a vision
dashboard running on a different machine. That watchdog POSTed `/stop` every 200 ms, and the
stop path internally sent `BalanceStand` before `Move(0,0,0)`. `BalanceStand` delivered to an
already-standing Go2 is a firmware safety fault. **A single D-pad press therefore armed a loop
that would eventually knock a standing 15 kg robot to the floor.**

The remote watchdog could not have known this. The knowledge lived in firmware, three network
hops away, and was undocumented by the vendor.

Anthropic's Model Hardware Standard reached the same conclusion from a different direction:
per QuEra, a launch partner, MHS enforces limits "at the hardware interface, independent of the
model," and Anthropic's own material describes safety checks blocking operations *before*
devices move. Genentech's evaluation blocked all six artificially induced failure conditions.

## 7.3 Stop categories — the distinction that matters most

IEC 60204-1 defines three stop categories. **They are not interchangeable, and a legged robot
makes the difference physical.**

| Category | Behavior | Use here |
|---|---|---|
| **Cat 0** | Immediate removal of power. Uncontrolled stop. | ⚠️ **Makes a quadruped fall.** |
| **Cat 1** | Controlled deceleration with power, then power removal at standstill. | **Emergency stop default** |
| **Cat 2** | Controlled stop, **power retained**. | **Mission abort / safe hold** |

**ISO 13850 permits only Cat 0 or Cat 1 for an emergency stop; Cat 2 is explicitly excluded.**
It also requires that an emergency stop **shall not create a new hazard** — and on a legged
robot, Cat 0 drops the machine, which is precisely a new hazard.

Boston Dynamics resolves this with three explicit levels, and their guidance is worth quoting:

> `ESTOP_LEVEL_NONE` · `ESTOP_LEVEL_SETTLE_THEN_CUT` · `ESTOP_LEVEL_CUT`
>
> *"Abruptly turning off motor power will cause the robot to drop; clients are encouraged to
> use SETTLE_THEN_CUT."*

**Adopt `CAT_1_SETTLE_THEN_CUT` as the default emergency stop for every legged archetype:**
come to a stop, sit down, then cut actuator power.

> **Never ship a control labeled "STOP" that is ambiguous about which category it invokes.**
> The mission-abort control and the emergency-stop control are different functions with
> different integrity requirements, and they must be visually and physically distinct. See
> [04_UX_SPEC.md](04_UX_SPEC.md) §4.8.

## 7.4 The heartbeat design — copy Spot's challenge/response

Spot's e-stop is a heartbeat-based software service, and one detail in it is worth adopting
verbatim: **each check-in carries a challenge, and the endpoint must reply with the one's
complement of that challenge.**

This matters because a naive `keepalive: true` message proves almost nothing. It can be
satisfied by a stale buffered packet, a replayed message, or a wedged thread echoing a
constant. A complement-of-challenge response proves the endpoint is actively *processing*.

The rest of Spot's protocol is equally worth copying:

- **Configuration declares the expected endpoints and each one's timeout** before anything runs.
- **Motors cannot power on** unless a valid configuration exists, *and* all endpoints are
  registered, *and* all have checked in at level NONE, *and* no endpoint has exceeded its
  timeout. Fail-closed by construction, not by a runtime check someone can forget.
- **Multiple independent endpoints, each with its own timeout.** The web UI, the mission
  executor, and any teleop client each hold an endpoint; any one going silent stops the robot.

### Two-tier heartbeats

Run **two independent heartbeats at different layers**:

| Tier | Between | Period | On expiry |
|---|---|---|---|
| **Local** | Safety Supervisor ↔ driver | tens of ms | Cat 2 hold |
| **Remote** | Operator/control plane ↔ robot | hundreds of ms | Mission-safe behavior |

> **The remote heartbeat must never be the only thing keeping motors alive.** Its expiry
> triggers a mission-safe behavior, not a power cut. The network is the thing that fails.

**Starting parameters** (from a single vendor-adjacent teleoperation source — treat as a
starting point to be validated, not as consensus): heartbeat at 10 Hz, watchdog at 500 ms
(five missed), velocity ramp-down over 200 ms then brakes, giving roughly 700 ms total stop
latency. Link health measured as the **interquartile range of RTT over 30 s** — under 10 ms
healthy, over 30 ms unacceptable.

The governing principle is worth stating plainly: **a stale control command is worse than no
command at all.** This is why teleoperation uses a WebRTC DataChannel in unreliable, unordered
mode. TCP head-of-line blocking adds 10–50 ms on loss and delivers commands that describe a
world that no longer exists.

> **Do not put a safety-relevant heartbeat on a WebSocket, a Foxglove bridge, or MQTT.** All
> are built around reliable ordered delivery and none specifies behavior on a lossy link.

## 7.5 Fault → response mapping

| Fault | Response | Category |
|---|---|---|
| Operator link loss | Stop in place, hold stance, motors powered, start secondary timer | **Cat 2** |
| Secondary timer expires | Controlled sit, then power down | **Cat 1** |
| Localization confidence collapse | Stop immediately, hold, request operator | **Cat 2** |
| Geofence breach imminent | Decelerate or reroute *before* the boundary | Planner constraint |
| Geofence breached | Stop, reverse along recorded path back inside | **Cat 2** |
| Battery below reserve | Abort mission, return to dock | Mission abort |
| Action plugin hang | Kill subprocess, apply mission failure policy | No motion change |
| Driver crash / unresponsive | Supervisor triggers stop, then Cat 1 on timeout | **Cat 2 → Cat 1** |
| Hardware e-stop pressed | Settle then cut, latched, manual reset required | **Cat 1** |

> **"Stop in place" is the only response that is safe to take without a valid plan.** Make it
> the fallback for every unclassified fault. A robot that stops is recoverable; a robot that
> improvises is not.

**Battery reserve is computed from distance home, not from a percentage.** A robot at 25% two
metres from the dock is fine; the same robot at 25% at the far end of a warehouse is not.

## 7.6 Geofencing

**Enforcement is on-robot. Always.** The control plane may author, distribute, and audit
geofences, and it must never be in the enforcement loop — because the network is exactly what
fails in the scenario the geofence exists to handle. A geofence enforced in the cloud is not a
geofence.

### Wire model

VDA 5050 `zoneSet`, distributed on the `zoneSet` topic and activated with `enableZoneSet`.
Zone types available: `BLOCKED`, `SPEED_LIMIT`, `ACTION`, `PRIORITY`, `PENALTY`, `DIRECTED`,
`BIDIRECTED`, `LINE_GUIDED`, `RELEASE`, `COORDINATED_REPLANNING`. Vertices are specified
counter-clockwise. Overlap resolution follows the standard's matrix, in which **`BLOCKED`
dominates everything** and the lowest `maximumSpeed` wins.

**Zone sets are immutable and versioned.** Editing produces a new `zoneSetId`; new sets arrive
`DISABLED` and must be explicitly enabled. Because a mission binds a specific zone-set version,
**a geofence edit invalidates affected missions rather than silently re-scoping them.** That
invalidation is a feature: it forces a human to re-validate a patrol after someone changes
where the robot is allowed to go.

### On-robot enforcement

Nav2 costmap filters are the standard mechanism — `KeepoutFilter` and `SpeedFilter`, driven by
filter masks and a `CostmapFilterInfo` message. Nav2 also supports polygon vector objects,
which suit operator-authored geofences better because polygons survive resolution changes and
remain editable in a UI.

> **Apply filters to both the local and the global costmap.** A global-only keepout can be
> locally violated during a recovery behavior — the robot backs up out of the allowed area
> while executing a recovery that never consulted the global map.

Prefer **predictive enforcement** — corridor constraints fed into the planner — over reactive
point-in-polygon testing. And **treat loss of localization confidence as itself a geofence
violation**: a robot that does not know where it is cannot know whether it is inside the fence.

## 7.7 Preflight validation

Match friction to consequence. Deploying a mission to a physical robot earns a **pre-flight
summary sheet**, not a yes/no dialog.

### Static checks — at authoring time

- Every waypoint inside the geofence and outside every `BLOCKED` zone.
- **Every recovery path and the return-to-dock route also checked against the geofence.** A
  return route passing through a keepout zone is the classic latent bug in this class of
  system, and it only manifests during an abort — the worst possible moment.
- Every `actionType` present in the archetype's factsheet.
- Every required `actionParameter` supplied, and type-checked against its declared
  `valueDataType`.
- Action preconditions satisfiable (required sensors declared and present).
- Node and edge counts within the factsheet's `protocolLimits.maximumArrayLengths`.
- Zone-set version binding still valid.
- Sequence numbering well-formed: nodes even, edges odd, continuous, `edges == nodes - 1`.

### Dynamic checks — at mission start

- `mobileRobotPosition.localized == true` **and** `localizationScore` above the archetype's
  declared `minimumScoreToStart`.
- `powerSupply.stateOfCharge` sufficient for the estimated mission duration **plus return
  reserve**.
- `safetyState.activeEmergencyStop == NONE` and `fieldViolation == false`.
- `operatingMode == AUTOMATIC`.
- No `errors[]` entry at `URGENT`, `CRITICAL`, or `FATAL`.
- Sensor liveness with fresh timestamps.
- E-stop chain continuity verified **before** enabling motors.
- Comms RTT and jitter baseline established.

> **On localization confidence as a gate.** The literature is consistent that many robots
> cannot self-diagnose localization reliability, and that this is a leading cause of serious
> navigation failures. VDA 5050 exposing `localizationScore` as a first-class field is
> precisely so this gate can exist. Use it. A silent 180° flip in a symmetric corridor is the
> failure mode you cannot afford, and it looks perfectly healthy from every other signal.

## 7.8 Relocalization — automatic with a human safety net

The recommended pattern, which trades a few seconds for eliminating a catastrophic failure mode:

1. Run a coarse global fix — **3D-BBS** (GPU branch-and-bound, roughly 878 ms average) against
   the saved tiled map.
2. **Present the candidate pose in the web UI with a confidence score, and let the operator
   confirm or drag to correct.**
3. On confirm, hand off to a tracking localizer publishing `map → odom` under Nav2.

VDA 5050's `initializePosition` action (`x, y, theta, mapId, lastNodeId`) is designed for
exactly step 2, and it converts a hard global-relocalization problem into an easy local one.

> Note that some localization initializers require the robot to be **still** during
> initialization. The robot should be standing, not stepping, when the operator seeds the pose.

## 7.9 Teleoperation safety

**The deadman is non-negotiable, and it is where safety credibility is won or lost with a
technical audience.**

- Motion commands are accepted **only while the deadman is actively held**. Release means an
  immediate zero-velocity command, not a coast.
- **Auto-release on window blur, tab hide, and pointer-leave.** Someone alt-tabbing must never
  leave a robot driving.
- Client-side watchdog: no acknowledgement within 300 ms shows `LINK STALE` and stops sending;
  1000 ms declares the link lost.
- **The server must independently stop the robot on command timeout.** The UI's job is to
  *tell the truth about* the safety mechanism, never to be it.
- Ramp velocity over ~250 ms rather than stepping from zero to commanded — a legged robot
  lurches otherwise.
- At RTT above 200 ms, **automatically cap maximum speed and say so on screen.** Visibly
  degrading capability is far better than letting someone drive blind.

## 7.10 Standards landscape

Editions verified September 2026. Paywalled numeric limits were not read.

| Standard | Status | Relevance |
|---|---|---|
| **ISO/CD 25785-1** | **Committee Draft** | *Safety requirements for dynamically stable industrial mobile robots (legged, wheeled, or other).* **This is the standard being written for exactly this product.** Scope covers robots with "actively controlled stability… could become unstable in the absence of power." Track it; consider joining the US TAG. |
| **ISO 13850:2015** | Current, 3rd ed. | Emergency stop. Only Cat 0 or Cat 1 permitted. Direct-opening mechanical latching, manual reset, reset permits but does not cause restart, must not create new hazards, red actuator on yellow background. |
| **IEC 60204-1** | Current | Stop categories 0/1/2. |
| **ISO 13849-1:2023** | Current; 2015 ed. withdrawn after 15 May 2027 | Performance Levels. PL d ≈ dual-channel, DC ≥ 90%. |
| **ISO 10218-1/-2:2025** | Feb 2025; US = ANSI/A3 R15.06-2025 | Biggest overhaul in 14 years. ISO/TS 15066 absorbed into Part 2. **"Collaborative" is now a property of the application, not the robot** — directly applicable, since *a mission is an application*: the same robot patrolling an occupied corridor versus a fenced yard are two different safety cases. Cybersecurity requirements added and tied to functional safety. Defers to ISO 3691-4 for mobility behaviors. |
| **ISO 3691-4:2023** | Current, 2nd ed.; revision in progress | Driverless industrial trucks. Out of scope as a compliance target, but the best source of mission-time design patterns — notably that **braking must stop the truck within the personnel-detection means' range**, i.e. detection range bounds speed. ⚠️ Numeric limits paywalled and unread. |
| **ANSI/A3 R15.08** | -1:2020, -2:2023; **-3 not published** | Part 3 covers users — who authorizes a mission, how the environment is validated, change management. It is aimed exactly at this layer and **does not exist yet.** ⚠️ Confirm status with A3. |
| **UL 3300:2024** | ANSI-approved Apr 2025 | Service, security, mobile, and **humanoid** robots for commercial use by non-skilled operators. **Most likely certification path for an inspection quadruped.** |

**A note on scope.** Every industrial standard above targets industrial trucks or robots in
industrial settings. A quadruped doing inspection patrols is not cleanly in scope for any of
them. They inform the design; they are not conformance targets without expert review. That gap
is why ISO/CD 25785-1 is being written.

## 7.11 The unresolved problem, stated plainly

**Perception lidar can plan; only safety lidar can stop.**

A certified safety scanner is a Type 3 device with hardwired dual-channel OSSD outputs that
drop motor power without any software involvement. A Nav2 stack cannot be in that path.

On a quadruped this is genuinely hard, and it is not solved by anyone: **a protective field is
defined in a plane relative to a body that pitches, rolls, and changes height with every
step.** The geometry that makes a safety field meaningful on an AGV does not transfer to a
legged machine.

This is unresolved in the standards, it is part of why ISO/CD 25785-1 exists, and this
specification does not solve it either. **State the limitation; do not paper over it.** The
correct engineering response given an unresolved protective-field problem is to reduce speed
rather than extend sensing range, since the required separation distance grows with system
latency and with speed.
