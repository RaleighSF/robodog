# 03 — Contracts & Data Model

> This is the most important document in the specification. Every schema the platform depends
> on is defined here. Where an open standard already defines a schema, we adopt it and say so.

## 3.0 Standards adopted, and their currency

| Standard | Version | Verified | Used for |
|---|---|---|---|
| **VDA 5050** | 3.0.0 (2026-03-19) | Schemas read directly | Mission, capability descriptor, state, geofence |
| **REP-103** | current | Source read | Units and axis conventions |
| **REP-105** | current | Source read | Coordinate frame tree |
| **MCAP** | 0.x spec | Spec read | On-robot recording |
| **Foxglove schemas** | current | Repo read | Well-known message types |
| **COPC** | 1.0 | — | Streamable point clouds |
| **Nav2 Route Server** | Jazzy+ | `.action` files read | Route graph, operations model |

**Rejected: MassRobotics AMR Interop Standard.** Last commit 2021-10-08. Two messages,
monitoring only — no order, node, edge, or action model. The promised v2.0 mission API never
shipped. VDA 5050 v3 supersedes it entirely.

> **Why VDA 5050 v3 specifically.** Version 3.0.0 was deliberately de-AGV-ified: `agvPosition`
> became `mobileRobotPosition`, `batteryState` became `powerSupply`, and the stated goal is
> integrating "mobile robots with higher levels of autonomy." A quadruped patrol platform is
> the case this revision was written for. Versions 2.x carry AGV-specific field names and
> should not be used.

### v2.x → v3.0 renames — most online examples are still 2.x

Nearly every VDA 5050 code sample, blog post, and AI-generated summary you will encounter
uses 2.1.0 names. Verified diff against the tagged schemas:

| 2.1.0 | 3.0.0 |
|---|---|
| `agvPosition` | **`mobileRobotPosition`** |
| `batteryState{batteryCharge, reach}` | **`powerSupply{stateOfCharge, range}`** |
| `*Description` (node/edge/action/map) | **`*Descriptor`** |
| `edge.startNodeId`, `edge.endNodeId` | **removed** — adjacency is `sequenceId` only |
| `edge.maxSpeed` / `maxHeight` / `minHeight` | `maximumSpeed` / `maximumMobileRobotHeight` / `minimumLoadHandlingDeviceHeight` |
| `edge.rotationAllowed` | `reachOrientationBeforeEntering` |
| `allowedDeviationXY` (float) | **object `{a, b, theta}`** — an ellipse |
| `blockingType` {NONE, SOFT, HARD} | **+ `SINGLE`** |
| `safetyState.eStop` {AUTOACK, MANUAL, REMOTE, NONE} | **`activeEmergencyStop`** {MANUAL, REMOTE, NONE} — `AUTOACK` gone |
| `operatingMode` | **+ `STARTUP`, `INTERVENED`**; `TEACHIN` → `TEACH_IN` |
| `connectionState` {…, `CONNECTIONBROKEN`} | **+ `HIBERNATING`**; `CONNECTION_BROKEN` |
| `errorLevel` {WARNING, FATAL} | **+ `URGENT`, `CRITICAL`** |
| `order.zoneSetId` | **removed** |
| timestamp `.ff` | **`.fff`** |

New in 3.0: the `zoneSet` and `responses` topics, `edge.corridor`, `state.plannedPath` /
`intermediatePath`, separate `instantActionStates` and `zoneActionStates` arrays,
`action.retriable` with the `RETRIABLE` status.

> **Two known schema-versus-prose inconsistencies in the standard itself.** The JSON schema
> says `maxRotationSpeed`; the spec markdown says `maximumRotationSpeed`. The schema and §7.5
> say `grantType`; §6.4.3 prose says `responseType`. **The VDA5050 repository README states the
> VDA PDF is authoritative where it and GitHub disagree** — check the PDF before implementing
> either field.

### Transport specifics

MQTT 3.1.1 minimum, JSON payloads. **QoS 0 for everything except `connection`, which is QoS 1**;
`connection` and `factsheet` use the retained flag. Set the MQTT Last Will and Testament to
`.../connection` with `CONNECTION_BROKEN` at connect time, then publish `ONLINE`. `state` is
published on relevant events and **at minimum every 30 seconds**.

---

## 3.1 Coordinate frames and units

**Adopt REP-103 and REP-105 without modification.** These are quoted rather than paraphrased
because subtle deviations here produce bugs that take days to find.

### Units (REP-103)

SI throughout: **meter, kilogram, second, ampere**; derived **radian, hertz, newton, watt,
volt, celsius, tesla**. All coordinate systems are **right-handed**.

- **Body frame: x forward, y left, z up.**
- **Short-range Cartesian geographic: ENU** — X east, Y north, Z up.
- **Camera optical frames** (suffix `_optical_frame`): z forward, x right, y down.
- Rotation representation preference: **quaternion → rotation matrix → fixed-axis roll-pitch-yaw
  about X, Y, Z**. Euler angles are discouraged — there are 24 valid conventions.

> **The heading bug you will otherwise ship.** REP-103: *"the yaw component of orientation
> increases as the child frame rotates counter-clockwise, and for geographic poses, yaw is zero
> when pointing east."*
>
> A compass bearing is zero at **north** and increases **clockwise**. These are different by a
> reflection and a 90° offset. Operators must see compass degrees; the wire format must carry
> REP-103 yaw. **Convert at exactly one boundary, in one function, with a unit test.**
> `compass_deg = (90 - degrees(yaw_rad)) mod 360`.

### Frame tree (REP-105)

Strictly `earth → map → odom → base_link`. Each frame has exactly one parent — which is why
`map` parents `odom` rather than both parenting `base_link`.

| Frame | Property | Consequence |
|---|---|---|
| `base_link` | Rigidly attached to the robot base | Sensor extrinsics are relative to this |
| `odom` | Continuous, **drifts without bound** | Good short-term local reference. **Never store a waypoint in odom.** |
| `map` | **Not continuous** — jumps discretely on relocalization | Good long-term global reference, poor for local sensing |
| `earth` | ECEF origin | Only needed for multi-map or multi-site |

**Frame authorities.** The odometry source broadcasts `odom → base_link`. The localization
component computes `map → base_link` but **broadcasts `map → odom`** — it receives
`odom → base_link` and subtracts. `earth → map` is normally static.

**Practical rules for this platform:**

1. **Every stored waypoint is in the `map` frame with an explicit map ID and version.**
2. One `map` frame per building floor. Align the map with the building, at floor level.
3. A `map` frame jump moves the robot relative to its waypoints — which is exactly why
   localization confidence gates mission start (§3.6).

---

## 3.2 Capability descriptor — the robot archetype

**Adopt the VDA 5050 v3 `factsheet` message.** This is a standardized, typed, versioned robot
capability descriptor that already contains action scopes and parameter data types. It is the
"archetype" feature, for free.

### Structure

```jsonc
{
  "headerId": 1,
  "timestamp": "2026-09-02T14:00:00.000Z",
  "version": "3.0.0",
  "manufacturer": "Unitree",
  "serialNumber": "go2-unit-01",

  "typeSpecification": {
    "seriesName": "Go2",
    "seriesDescription": "Unitree Go2 quadruped, EDU variant with Livox Mid-360",
    "mobileRobotKinematics": "LEGGED",
    "mobileRobotClass": "INSPECTION",
    "maximumLoadMass": 5.0,
    "localizationTypes": ["NATURAL"],
    "navigationTypes": ["AUTONOMOUS"],
    "supportedZones": ["BLOCKED", "SPEED_LIMIT", "ACTION"]
  },

  "physicalParameters": {
    "minimumSpeed": 0.0,      "maximumSpeed": 0.25,
    "minimumAngularSpeed": 0.0, "maximumAngularSpeed": 0.5,
    "maximumAcceleration": 0.5, "maximumDeceleration": 1.0,
    "minimumHeight": 0.22,    "maximumHeight": 0.40,
    "width": 0.31,            "length": 0.70
  },

  "protocolLimits": {
    "maximumArrayLengths": { "order.nodes": 200, "node.actions": 16 },
    "timing": {
      "minimumOrderInterval": 1.0,
      "minimumStateInterval": 0.2,
      "defaultStateInterval": 1.0,
      "visualizationInterval": 0.1
    }
  },

  "protocolFeatures": {
    "mobileRobotActions": [
      {
        "actionType": "capture_image",
        "actionDescription": "Capture a still image from a named camera.",
        "actionScopes": ["NODE", "INSTANT"],
        "actionParameters": [
          { "key": "camera", "valueDataType": "STRING",
            "description": "Sensor id, e.g. front_rgb", "isOptional": false },
          { "key": "resolution", "valueDataType": "STRING",
            "description": "One of: full, 1080p, 720p", "isOptional": true }
        ],
        "actionResult": "Capture id of the stored image.",
        "blockingTypes": ["SOFT", "HARD"],
        "pauseAllowed": true,
        "cancelAllowed": true
      }
    ]
  },

  "mobileRobotGeometry": { "envelopes2d": [ /* footprint polygon */ ] },

  // ── OmniControl extension. Namespaced; not part of VDA 5050. ──
  "x-omnicontrol": {
    "safetyLimits":    { /* §3.3 */ },
    "postureStates":   { /* §3.4 */ },
    "livenessProfile": { /* §3.5 */ },
    "sensors":         { /* §3.7 */ },
    "persona":         { /* §3.8 */ }
  }
}
```

> **Field-name warning.** The capability list is `protocolFeatures.mobileRobotActions`. Some
> secondary documentation and at least one AI-generated summary calls it `agvActions` — that
> was the 2.x name and it is wrong for v3. Trust the JSON schema in the VDA 5050 repository
> over any prose description.

### Where the descriptor comes from

Two sources merge into one document:

1. **Static, per archetype** — kinematics, safety limits, posture states, liveness profile.
   Authored by the driver developer, checked into the driver package.
2. **Dynamic, discovered at runtime** — the action list, assembled by scanning the plugin
   directory (§3.8), filtered to actions this archetype supports.

The Action Registry publishes the merged document. **The mission editor offers only actions
present in the selected archetype's descriptor.** This single rule is what makes the archetype
picker work and prevents authoring a mission the robot cannot run.

---

## 3.3 Safety limits — the MHS-aligned contract

MHS's confirmed semantics are that a device declares **what it can measure, what can be
adjusted, and what safety limits are enforced**, and that limits are enforced in the driver,
below and independent of the model. Our extension expresses exactly that.

```jsonc
"safetyLimits": {
  "velocity": {
    "vx":   { "min": -0.15, "max": 0.25, "unit": "m/s" },
    "vy":   { "min": -0.20, "max": 0.20, "unit": "m/s" },
    "vyaw": { "min": -0.50, "max": 0.50, "unit": "rad/s" }
  },
  "commandRate": { "minIntervalSeconds": 2.0, "appliesTo": ["posture"] },
  "battery": {
    "missionStartMinimum": 0.40,
    "returnReserve":       0.20,
    "criticalStop":        0.10
  },
  "geofence":     { "enforcement": "ON_ROBOT", "requiredZoneTypes": ["BLOCKED"] },
  "localization": { "minimumScoreToStart": 0.75, "minimumScoreToContinue": 0.50 },
  "estop": {
    "supportedCategories": ["CAT_1_SETTLE_THEN_CUT", "CAT_2_HOLD"],
    "default": "CAT_1_SETTLE_THEN_CUT"
  }
}
```

**Every limit here is enforced by the Safety Supervisor on the edge runtime, before the
command reaches the driver.** The UI *also* displays and pre-validates against them, purely so
the operator sees the constraint early. The UI's copy is advisory; the supervisor's is
authoritative. If they disagree, the supervisor wins and the discrepancy is logged as a defect.

> **On `CAT_1_SETTLE_THEN_CUT` as the default for legged robots.** A Category 0 stop removes
> power immediately, which makes a quadruped *fall*. ISO 13850 forbids an emergency stop that
> creates a new hazard. Boston Dynamics resolves this with an explicit
> `ESTOP_LEVEL_SETTLE_THEN_CUT` — come to a stop, sit down, then cut actuator power — and
> their own guidance is to prefer it. Adopt the same default. See [07_SAFETY.md](07_SAFETY.md).

---

## 3.4 Posture state machine

The Go2 experience proved that a legged robot's firmware has **posture-dependent safety
faults that are invisible from the API surface**. Sending `BalanceStand` to an already-standing
Go2 is a fault. Re-selecting the motion controller mode while standing is a fault. Neither is
documented by the vendor; both were discovered by watching a robot fall.

The predecessor encoded this as `if posture == 'standing'` string comparisons scattered across
nine call sites. **Make it a declarative transition table owned by one component.**

```jsonc
"postureStates": {
  "initial": "unknown",
  "states": ["unknown", "idle", "standing", "sitting", "moving", "faulted"],
  "transitions": [
    { "from": "idle",     "to": "standing", "via": "stand",  "guard": null },
    { "from": "standing", "to": "moving",   "via": "move",   "guard": "DENY",
      "denyReason": "Go2 firmware faults if Move is issued while standing. Crouch first." },
    { "from": "idle",     "to": "moving",   "via": "move",   "guard": null },
    { "from": "standing", "to": "idle",     "via": "crouch", "guard": null }
  ],
  "forbiddenCommands": [
    { "state": "standing", "command": "balance_stand",
      "reason": "Firmware safety fault: BalanceStand while in StandUp posture causes a fall." },
    { "state": "standing", "command": "set_motion_mode",
      "reason": "Firmware safety fault: mode reselection while standing causes a fall." }
  ],
  "externalTakeover": {
    "detectedBy": "teleop_source_active",
    "action": "reset_to_unknown",
    "reason": "A human with a handheld controller may move the robot to any posture."
  }
}
```

**Rules:**

1. Every motion command is checked against this table before dispatch. A `DENY` guard returns
   a structured refusal carrying `denyReason` — which surfaces verbatim to the operator, so the
   UI never has to hardcode vendor-specific explanations.
2. The table is **data**, loaded from the descriptor. Adding a robot with different firmware
   quirks means editing JSON, not editing the executor.
3. `externalTakeover` is mandatory. Any robot with a physical remote can have its posture
   changed behind the platform's back, and continuing to believe a stale posture is how the
   predecessor deadlocked its own keepalive.

---

## 3.5 Liveness profile

A legged robot needs **multiple independent liveness clocks at different layers, and they are
not interchangeable.** Using the wrong one at the wrong moment is actively harmful. The Go2
requires three, and discovering the third took four commits and several falls.

```jsonc
"livenessProfile": {
  "transport": {
    "intervalSeconds": 2.0,
    "description": "Protocol-level keepalive. Channel dies without it.",
    "onExpiry": "reconnect"
  },
  "controllerMode": {
    "intervalSeconds": 30.0,
    "description": "Robot drops to a non-commandable mode after 30-45s idle.",
    "suppressInStates": ["standing"],
    "suppressReason": "Mode reselection while standing causes a fall.",
    "onExpiry": "resend"
  },
  "posture": {
    "intervalSeconds": 300.0,
    "command": "stand",
    "channel": "sport",
    "description": "Firmware safety-faults ~10 min after StandUp with no further sport traffic.",
    "activeInStates": ["standing"],
    "onExpiry": "resend"
  }
}
```

> **The subtle part, and the reason this is a first-class contract.** The Go2's transport
> heartbeat runs every 2 seconds and is completely insufficient to prevent the posture
> timeout — the firmware requires *sport-channel* traffic specifically. Meanwhile the
> controller-mode keepalive, which looks like the obvious thing to send, **causes a fall** if
> sent while standing. So one heartbeat must be suppressed in exactly the state where another
> must be active. No amount of generic "send a keepalive" logic discovers this.

---

## 3.6 Mission model

**Adopt VDA 5050 v3 `order` semantics.** Nodes are waypoints, edges are segments, actions
attach to either.

### Mission document

```jsonc
{
  "missionId": "msn_7f3a2b",
  "missionVersion": 4,
  "name": "North Wing Night Patrol",
  "archetype": "unitree-go2",
  "mapId": "map_plano_floor2",
  "mapVersion": 7,

  // OmniControl field. VDA 5050 v3.0 REMOVED order.zoneSetId — on the wire,
  // zone sets are distributed on the `zoneSet` topic and activated with the
  // enableZoneSet action. We bind it here so a mission is pinned to the exact
  // geofence version it was validated against; the deployer translates.
  "zoneSetId": "zs_plano_floor2_v3",

  "playbackMode": { "type": "periodic", "intervalSeconds": 3600, "repetitions": 8 },

  "defaultFailureBehavior": {
    "type": "retry", "maxAttempts": 2,
    "thenType": "return_to_dock_and_report"
  },

  "nodes": [
    {
      "nodeId": "n_01",
      "sequenceId": 0,
      "released": true,
      "nodeDescriptor": "Electrical panel 2A",
      "nodePosition": {
        "x": 12.42, "y": -3.08, "theta": 1.5708,
        "mapId": "map_plano_floor2",
        "allowedDeviationXY": { "a": 0.25, "b": 0.25, "theta": 0.0 },
        "allowedDeviationTheta": 0.17
      },
      "actionPose": null,
      "headingMode": "LOCKED",
      "actions": [
        {
          "actionId": "a_01",
          "actionType": "capture_image",
          "actionDescriptor": "Panel 2A thermal check",
          "blockingType": "HARD",
          "retriable": true,
          "actionParameters": [
            { "key": "camera", "value": "front_rgb" },
            { "key": "resolution", "value": "full" }
          ],
          "siteElementId": "se_panel_2a"
        }
      ]
    }
  ],

  "edges": [
    {
      // NOTE: no startNodeId/endNodeId. Removed in VDA 5050 v3.0 —
      // adjacency is derived purely from sequenceId. Edge n connects
      // the nodes at sequenceId n-1 and n+1.
      "edgeId": "e_01", "sequenceId": 1, "released": true,
      "maximumSpeed": 0.20,
      "orientationType": "TANGENTIAL",
      "corridor": { "leftWidth": 0.8, "rightWidth": 0.8,
                    "corridorReferencePoint": "KINEMATIC_CENTER" },
      "actions": []
    }
  ]
}
```

### Rules inherited from VDA 5050

| Rule | Detail |
|---|---|
| **Sequence numbering** | Nodes even (0, 2, 4…), edges odd (1, 3, 5…), continuous. `edges == nodes - 1`. **This is also the adjacency mechanism** — v3.0 deleted `startNodeId`/`endNodeId`, so edge *n* connects the nodes at *n−1* and *n+1*. Renumbering is therefore never safe on a live order. |
| **First node** | Must be trivially reachable and always `released`. It is **not** reported in `nodeStates`. |
| **The base cannot be changed** | Fleet control must assume base nodes are already executed. Order updates reuse `orderId` with an incremented `orderUpdateId`, and the update's first node must be the previous order's **last base node** (the *stitching node*), resent in full. Prior base nodes are never retransmitted. Once assigned and released, a `sequenceId` never changes. |
| **Timestamps** | `YYYY-MM-DDTHH:mm:ss.fffZ` — **millisecond** precision. v2.x used `.ff` (centiseconds). |
| **Idle** | `nodeStates` and `edgeStates` empty *and* every `actionState` FINISHED or FAILED. New orders are accepted only when idle; updates are accepted while running. |
| **Base / horizon** | `released: true` = authorized to execute. `false` = planned only. **After an unreleased edge, no released node or edge may follow.** |
| **Blocking types** | `NONE` = parallel, driving allowed. `SOFT` = parallel, no driving. `SINGLE` = not parallel, driving allowed *(new in v3)*. `HARD` = neither. |
| **Deviation** | `allowedDeviationXY` is an ellipse `{a, b, theta}`; `allowedDeviationTheta` is radians. This is arrival tolerance, and it must be operator-visible. |

### Three deliberate additions

**1. `actionPose` — separating the navigation target from the observation pose.**

Borrowed from Boston Dynamics, whose `Element` splits `destination_waypoint_id` from
`destination_waypoint_tform_body_goal`. **A robot rarely wants to stand exactly on the point it
inspects from.** Naive designs conflate the two and then discover that the ideal camera
position is inside a wall. When `actionPose` is null, the node position is used.

**2. `headingMode`** — `AUTO` (face the next waypoint) or `LOCKED` (explicit theta).
**Defaults to `AUTO`.** This is the single highest-leverage ease-of-use decision in the
product: most operators never touch heading, and those who need it get a lock with a visible
indicator.

**3. `siteElementId`** — a reference to a reusable action definition (§3.7).

### Runtime state — adopt VDA 5050 `state`

The robot publishes `state` at 1 Hz and `visualization` at 10 Hz. Fields that matter most:

- `mobileRobotPosition: {x, y, theta, mapId, localized, localizationScore, deviationRange}` —
  **`localizationScore` is the safety gate.** Literature is clear that many robots cannot
  self-diagnose localization reliability, and that this causes serious navigation failures.
- `actionStates[]: {actionId, actionType, actionStatus, actionResult}` where status ∈
  `WAITING | INITIALIZING | RUNNING | PAUSED | RETRIABLE | FINISHED | FAILED`.
- `safetyState: {activeEmergencyStop: MANUAL|REMOTE|NONE, fieldViolation}`.
- `operatingMode ∈ STARTUP | AUTOMATIC | SEMIAUTOMATIC | INTERVENED | MANUAL | SERVICE | TEACH_IN`.
- `powerSupply: {stateOfCharge, batteryVoltage, batteryCurrent, batteryHealth, charging, range}`.
- `errors[].errorLevel ∈ WARNING | URGENT | CRITICAL | FATAL`.

`RETRIABLE` deserves attention: it is the state where an action failed but the operator may
resolve it. The standard defines `retry{actionId}` and `skipRetry{actionId}` instant actions
for exactly this. **Build the UI affordance for it** — it converts a failed patrol into a
completed one.

---

## 3.7 Actions: the plugin contract

### Site elements — actions are reusable library entities

**An action definition is a first-class object referenced by missions, not a child of one.**
This follows Orbit's `SiteElement` and ANYbotics' "inspection point."

The reason is concrete: it is what makes "how has electrical panel 2A changed over six months"
answerable, and what allows re-running a single inspection without running the mission it
belongs to. Embedding action definitions inside missions forecloses both, permanently, and the
migration later is painful.

```jsonc
{
  "siteElementId": "se_panel_2a",
  "name": "Electrical Panel 2A",
  "mapId": "map_plano_floor2",
  "actionType": "capture_image",
  "actionParameters": [ { "key": "camera", "value": "front_rgb" } ],
  "defaultPose": { "x": 12.42, "y": -3.08, "theta": 1.5708 },
  "tags": ["electrical", "thermal", "quarterly"]
}
```

### Plugin discovery

Action plugins are Python files in a directory. The Action Registry scans it, imports each,
reads the declaration, and publishes the merged capability list.

```
actions/
├── capture_image.py
├── read_gas_sensor.py
├── perform_gesture.py
├── measure_distance.py
└── vendor/
    └── acme_thermal_probe.py
```

### The plugin interface — tick-based, not blocking

```python
from omnicontrol.actions import Action, ActionContext, ActionResult, Status, param

class CaptureImage(Action):
    action_type   = "capture_image"
    description   = "Capture a still image from a named camera."
    scopes        = ["NODE", "INSTANT"]
    blocking      = ["SOFT", "HARD"]
    pause_allowed = True
    cancel_allowed = True

    # Typed parameters → generates the factsheet entry AND the UI form.
    camera = param.String(
        description="Sensor id to capture from",
        choices_from="sensors.cameras",   # resolved from the capability descriptor
        required=True,
    )
    resolution = param.Enum(
        description="Capture resolution",
        values=["full", "1080p", "720p"],
        default="full",
    )

    # Preconditions are declarative so the Validator can check them statically.
    requires_sensors  = ["{camera}"]
    requires_stopped  = True
    estimated_seconds = 2.0

    def on_start(self, ctx: ActionContext) -> None:
        self._handle = ctx.sensors.request_frame(self.camera, self.resolution)

    def on_tick(self, ctx: ActionContext) -> Status:
        if not self._handle.ready:
            return Status.RUNNING
        capture_id = ctx.captures.write_image(
            self._handle.frame,
            metadata={"camera": self.camera, "node_id": ctx.node_id},
        )
        self._result = {"capture_id": capture_id}
        return Status.SUCCESS

    def on_stop(self, ctx: ActionContext, reason: str) -> None:
        self._handle.release()

    def result(self) -> ActionResult:
        return ActionResult(data=self._result)
```

**Why tick-based rather than a blocking `run()`.** This is Boston Dynamics' Remote Mission
Service protocol — `EstablishSession` → repeated `Tick` → `Stop` → `TeardownSession` — and it
is chosen because **it is what survives pause and resume.** A blocking call cannot be paused,
cannot report incremental progress, and cannot be cancelled cleanly when an e-stop fires.

**Explicitly rejected: the Nav2 `WaypointTaskExecutor` interface.**

```cpp
virtual bool processAtWaypoint(const geometry_msgs::msg::PoseStamped& curr_pose,
                               const int& curr_waypoint_index) = 0;
```

One plugin per node, a boolean return, no result payload, no parameters. It cannot carry a
measurement, which is the entire point of an inspection action. Nav2's **Route Server
operations** model (`{type, trigger: ON_ENTER|ON_EXIT|ON_NODE_ACHIEVED, metadata}`) is much
closer and worth mirroring for trigger semantics.

### Isolation and limits

- Each invocation runs in a **subprocess**. A plugin segfault must not take down the executor.
- A hard timeout comes from `estimated_seconds × 3`, floor 10 s, overridable per action.
- Plugins get a capability-scoped context object. They **cannot command motion** — a plugin
  needing the robot to move requests it through `ctx.motion`, which routes through the Safety
  Supervisor like everything else.
- Filesystem access is restricted to the capture directory.

### Results and captures

`ActionResult.data` is JSON, size-capped at 64 KB. Anything larger is a **capture** — written
via `ctx.captures.*`, which returns an ID, stores the blob on the robot, and enqueues it for
sync. Never return a blob through the result channel.

---

## 3.8 Sensors and persona

### Sensor declaration

Sensors are declared in the descriptor and addressed by URI, replacing the predecessor's enum
of vendor-specific strings.

```jsonc
"sensors": {
  "cameras": [
    { "id": "front_rgb",
      "uri": "go2webrtc://front",
      "resolution": [1920, 1080],
      "extrinsics": { "frame": "base_link",
                      "translation": [0.28, 0.0, 0.12],
                      "rotation_rpy": [0.0, 0.0, 0.0] } }
  ],
  "lidar": [
    { "id": "mid360", "uri": "livox://192.168.123.120",
      "type": "non_repetitive", "rateHz": 10, "minRange": 0.3, "maxRange": 40.0,
      "extrinsics": { "frame": "base_link",
                      "translation": [0.10, 0.0, 0.22],
                      "rotation_rpy": [0.0, 0.0, 0.0] } }
  ]
}
```

**Extrinsics are mandatory, not optional.** The predecessor's gesture detector hardcoded
geometry calibrated to a 12-inch camera height — a reaching arm points *downward* and shoulders
are usually cropped out. Every one of those rules inverts on a chest-height mount. Perception
logic must consume extrinsics as parameters.

### Persona

The predecessor hardcoded, as a module-level string, *"You ARE a Unitree GO2 robot dog. This
camera is YOUR eyes … at ground level."* Deploying on any other robot required editing the
perception module.

```jsonc
"persona": {
  "embodiment": "a four-legged inspection robot",
  "viewpointHeight": 0.30,
  "viewpointDescription": "near ground level, looking slightly upward at people",
  "selfVisibility": "Your own legs may appear at the lower edges of the frame."
}
```

Prompts are templates rendered from these fields.

---

## 3.9 The agent interface — MCP and MHS

### What is actually confirmed about MHS

As of 2026-09-02 there is **no published MHS specification** — one announcement post and an
application-gated research preview. Five architectural facts are confirmed from Anthropic's
own material:

1. The **driver** is the unit of integration; the primitives are **`read`** and **`write`**.
2. Drivers carry **natural-language tags**, from which a **reference file** is auto-generated
   declaring what can be measured, what can be adjusted, and what limits are enforced.
3. There are **three access mechanisms: MCP, a CLI, and code files (APIs).** MHS is
   model-agnostic; MCP is one front-end, not the substrate. The press framing "MCP for
   hardware" is a journalist's analogy and misdescribes the layering.
4. **Safety limits are enforced in the driver, below and independent of the model**, blocking
   before motion.
5. **Continuous telemetry lives in a shared-memory state dictionary** readable by any attached
   process; the agent supervises *above* the real-time control loop, never inside it.

Not published: the reference file format, field names, transport, discovery, auth, rate
limiting, e-stop protocol, versioning, or license. **Do not build against guessed identifiers.**

> **A structural risk worth internalizing.** Because the reference file is auto-generated from
> natural-language tags, MHS may not have a stable machine schema at all in the way one would
> assume. Designing our contracts against invented field names would be a category error. We
> design against the *semantics* — measure / adjust / limit — which are confirmed.

### How this platform aligns

| MHS semantic | Our implementation |
|---|---|
| What it can measure | `sensors` + `state` message fields |
| What can be adjusted | `protocolFeatures.mobileRobotActions` + motion commands |
| Safety limits enforced | `x-omnicontrol.safetyLimits`, enforced by the Safety Supervisor |
| `read` / `write` primitives | Driver interface (§3.10) exposes exactly these two |
| Shared-memory state dictionary | The edge State Store (see [02_ARCHITECTURE.md](02_ARCHITECTURE.md) §2.6) |
| Natural-language tags | `description` on every action, parameter, and sensor |

**Every description field in every contract is written for a model to read.** This is not
decoration — it is the interface. Write `"Capture a still image from a named camera"`, never
`"img cap"`.

### MCP server surface

The control plane exposes an MCP server so an agent can operate the platform:

| Tool | Purpose |
|---|---|
| `list_robots` | Robots, archetypes, state, availability |
| `get_capability_descriptor` | Full factsheet for an archetype |
| `list_maps` / `get_map_metadata` | Available maps, bounds, zone sets |
| `list_missions` / `get_mission` | Mission definitions |
| `create_mission` / `update_mission` | Author missions programmatically |
| `validate_mission` | Run the full validator, return structured findings |
| `deploy_mission` | **Requires human approval.** Returns a pending-approval handle. |
| `get_run_status` | Live or historical run state |
| `list_captures` / `get_capture` | Retrieve captured data |
| `emergency_stop` | Always available, never gated |

> **`deploy_mission` and every motion command require explicit human approval.** MHS's own
> research preview observed agents "stopped to wait for human confirmation before performing
> an action it deemed even slightly risky," with the note that an overly cautious agent is
> preferable. Enforce that at the protocol level rather than relying on the model's judgment.

### The MHS adapter

Build the platform against our own driver interface (§3.10). When MHS opens, add
`drivers/mhs_adapter.py` translating our interface to MHS `read`/`write`. Two consequences:
we ship now, and any MHS-native device becomes usable through the same adapter in reverse.

---

## 3.10 The driver interface

Every robot driver implements this. It is intentionally small — `read` and `write` plus
lifecycle — to align with MHS primitives.

```python
class RobotDriver(Protocol):
    # ── Lifecycle ──
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    @property
    def connection_state(self) -> ConnectionState: ...   # ONLINE|OFFLINE|HIBERNATING|BROKEN

    # ── Descriptor ──
    def capability_descriptor(self) -> Factsheet: ...

    # ── MHS-aligned primitives ──
    async def read(self, key: str) -> Any:
        """Read a declared measurable. Keys come from the descriptor."""
    async def write(self, key: str, value: Any) -> WriteResult:
        """Adjust a declared adjustable. MUST enforce declared safety limits and
        MUST reject transitions forbidden by the posture state machine, returning
        a structured refusal carrying the human-readable reason."""

    # ── Streaming ──
    def subscribe(self, key: str, callback: Callable) -> Subscription: ...

    # ── Motion (a typed convenience over write) ──
    async def command(self, verb: str, **params) -> CommandResult: ...
    async def stop(self, category: StopCategory) -> None: ...
```

**Contract requirements for every driver:**

1. **`write` enforces limits.** Not the caller. Never the UI.
2. **Refusals are structured and human-readable.** `{allowed: false, reason: "...", code: "..."}`.
   The UI displays `reason` verbatim, so vendor quirks never need hardcoding upstream.
3. **The driver owns exactly one connection and contains no restart logic.** Recovery is the
   Supervisor's job. This is the direct lesson from a service that broke with
   `RuntimeError: cannot reuse already awaited coroutine` when watchdog logic was added inside it.
4. **The driver never touches the filesystem or the network beyond its robot.**
5. **Liveness clocks run inside the driver**, driven by the descriptor's liveness profile.

---

## 3.11 Maps

```jsonc
{
  "mapId": "map_plano_floor2",
  "mapVersion": 7,
  "name": "Plano Innovation Center — Floor 2",
  "frame": "map",
  "createdBy": "run_2f8a91",
  "origin": { "latitude": 33.0198, "longitude": -96.6989, "altitude": 180.0,
              "yawToEnu": 0.0 },
  "bounds": { "min": [-40.0, -25.0, -1.0], "max": [60.0, 35.0, 4.0] },
  "artifacts": {
    "pointCloud":    { "format": "COPC",           "uri": "s3://…/cloud.copc.laz",   "points": 8400000 },
    "occupancyGrid": { "format": "ros_map_server", "uri": "s3://…/grid.yaml",        "resolution": 0.05 },
    "poseGraph":     { "format": "g2o",            "uri": "s3://…/graph.g2o" },
    "tiles":         { "format": "pcd_tiled",      "uri": "s3://…/tiles/",           "tileSize": 20.0 }
  },
  "slam": { "algorithm": "rko_lio", "version": "…",
            "lidar": "livox_mid360", "extrinsicsHash": "sha256:…" }
}
```

**Format choices:**

- **COPC** for browser delivery — LAZ with an internal octree in a single file, streamable by
  HTTP range request. Best modern option; avoids the Potree conversion pipeline.
- **Tiled PCD + a separate pose graph** for on-robot relocalization, with a JSON manifest
  carrying frame, origin, tile index, and the lidar/IMU extrinsics used. Mirror the Autoware
  bundle layout even if Autoware is not used.
- **`nav_msgs/OccupancyGrid`** conventions for 2D: row-major from (0,0), `0` unoccupied,
  `100` occupied, **`-1` unknown**, and origin is *the real-world pose of the bottom-left corner
  of cell (0,0)*.

> **Extrinsics hash.** A map built with one lidar mounting is not valid for a robot with a
> different one. Store the hash and refuse to load a map whose extrinsics do not match the
> robot attempting to use it. This failure is otherwise silent and presents as inexplicable
> localization drift.

### Zone sets — geofences

Adopt VDA 5050 `zoneSet`. Zone types: `BLOCKED`, `LINE_GUIDED`, `RELEASE`,
`COORDINATED_REPLANNING`, `SPEED_LIMIT`, `ACTION`, `PRIORITY`, `PENALTY`, `DIRECTED`,
`BIDIRECTED`.

**Zone sets are immutable and versioned by `zoneSetId`.** Editing produces a new ID; it never
mutates in place. A mission references a specific zone-set version, so **a geofence edit
invalidates affected missions rather than silently re-scoping them.** That invalidation is a
feature: it forces a human to re-validate a patrol after someone changes where the robot may go.

---

## 3.12 Captures and telemetry

### Three-level hierarchy

Adopt Orbit's model: **Run → RunEvent → Capture**.

```
Run          one execution of a mission (or one teleop session)
 └─ RunEvent one action invocation at one waypoint
     └─ Capture  one artifact: image, measurement, point cloud
```

**Model teleop sessions as Runs too.** This is why Orbit can put all data in one schema, and
it means "show me everything from Tuesday" works without special-casing.

Join key: `{missionId, runId, nodeId, actionId, timestamp}`.

### On-robot recording: MCAP

```
Magic · Header · Data section · [Summary] · [Summary Offset] · Footer · Magic
```

MCAP gives attachments (images), metadata records (the mission manifest), and indexed seeking
— the Run/RunEvent/Capture hierarchy expressed as a single file. Schema encodings supported:
`ros2msg`, `protobuf`, `jsonschema`, `flatbuffer`, `omgidl`.

Use **Foxglove well-known schemas** for standard types so any Foxglove-compatible tool can open
a recording: `PointCloud`, `CompressedImage`, `CompressedVideo`, `FrameTransform`, `LaserScan`,
`PoseInFrame`, `Log`, `Grid`, `SceneUpdate`, `LocationFix`, `Odometry`, `Event`.

### Sync to object storage

Hive-partitioned, which the predecessor already got right:

```
v1/runs/year=2026/month=09/day=02/hour=14/run_<id>.mcap
v1/captures/year=…/…/cap_<id>.<ext>
v1/events/year=…/…/evt_<id>.json
```

Store-and-forward with a local queue. **Never drop silently** — the predecessor's exporter
dropped events on a full deque and failed uploads without retry. Every drop must produce a
`WARNING`-level entry in the run record so a gap in the data is visible as a gap rather than
looking like an absence of findings.

### Event envelope

```jsonc
{
  "schemaVersion": "2.0.0",
  "eventId": "evt_20260902T140000Z_a1b2c3d4",
  "eventType": "run.started | run.completed | action.completed | action.failed | alert | heartbeat",
  "fleetId": "ntt-plano",
  "robotId": "go2-unit-01",
  "robotModel": "unitree-go2",
  "runId": "run_2f8a91",
  "missionId": "msn_7f3a2b",
  "sessionId": "sess_…",
  "timestamp": "2026-09-02T14:00:00.123Z",
  "payload": { /* type-specific */ }
}
```

Changes from the predecessor's 1.0.0 schema, each fixing a real defect:

- `fleetId` + `robotId` + `robotModel` replace a hardcoded `"go2-unit-01"` literal.
- `eventType` is a **closed enum**. The predecessor produced open-ended `"alert:<subtype>"`
  strings by string concatenation.
- Robot-specific health moves into a typed extension rather than fixed columns like
  `go2_service_reachable` and `rtsp_server_running`.
- The predecessor's `emit_alert` accepted a `message` parameter and **silently discarded it**.
  Payloads here are schema-validated at emission.

### Webhooks

Keep the surface tiny. Orbit ships exactly two event types, and that restraint is correct:

- `ACTION_COMPLETED`
- `ACTION_COMPLETED_WITH_ALERT`

HMAC-SHA256 signed. Resist the urge to emit forty event types; consumers will subscribe to all
of them and then complain about volume.
