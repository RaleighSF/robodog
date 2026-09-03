# 01 — Overview & Product Definition

## 1.1 The product in one paragraph

OmniControl is a web-based mission control platform for autonomous inspection robots. An
operator picks a **robot archetype**, then either drives the robot around a facility to build
a 3D map or loads a map built earlier. On that map they compose a **mission**: a sequence of
waypoints, each with a position, a facing direction, and zero or more **actions** — take a
photo, read a sensor, run a gesture, execute an arbitrary Python plugin. The finished mission
is validated, deployed to the physical robot, and executed autonomously. Everything the robot
captured is written to on-robot storage and optionally synced to cloud object storage for
analysis.

## 1.2 Why this exists

Three observations motivate the product.

**The mission-authoring layer is where the value is, and it is missing from every quadruped
except Spot.** Boston Dynamics has a mature stack — Autowalk for authoring, GraphNav for maps,
Orbit for fleet management, reusable actions, per-action failure policy, docking integration,
run archives, webhooks. Unitree, whose robots cost roughly a fifth as much, has **no
mission-authoring API at any tier.** The Go2 with an L2 lidar can record a path and replay it;
it cannot attach an action to a waypoint, cannot express a failure policy, and has no capture
model. The G1 humanoid has no mission layer at all.

**The fleet-observability layer has already commoditized.** Rocos was absorbed into
DroneDeploy. Foxglove repositioned away from robot dashboards entirely. The differentiation is
not in showing telemetry — it is in the mission domain model.

**Physical AI is standardizing right now, and being early is cheap.** VDA 5050 v3.0.0 shipped
in March 2026 explicitly rebuilt for "mobile robots with higher levels of autonomy." Anthropic
released MHS in August 2026. ISO/CD 25785-1, the first safety standard for dynamically stable
legged robots, is in committee draft. Building on these now costs almost nothing and produces
a platform that is interoperable by construction.

## 1.3 Users

**Nadia — Field Operator.** Runs the robot day to day at a facility. Comfortable with an
iPad and a game controller; not a roboticist. Needs to add a new inspection point in under two
minutes without asking anyone. Cannot be expected to understand coordinate frames, and should
never see the word "quaternion."

**Marcus — Robotics Engineer.** Integrates a new robot model, writes action plugins, debugs a
mission that failed at waypoint 7. Lives in the logs and wants raw access to everything. Needs
the platform to get out of his way and to never hide a real error behind a friendly message.

**Priya — Operations Manager.** Does not touch the robot. Wants to know that last night's
patrol ran, what it found, how it compares to last week, and whether the fleet is healthy.
Consumes reports and dashboards, not the 3D editor.

**Claude — the agent.** Increasingly, missions will be authored, adapted, and supervised by an
AI agent rather than a human. This is not speculative: it is what MHS exists for. Every
contract in this spec is designed to be **legible to a model** — natural-language descriptions
alongside typed schemas, explicit safety limits, and semantic action names rather than opaque
IDs. See [03_CONTRACTS.md](03_CONTRACTS.md) §3.9.

## 1.4 Scope

### In scope for v1

- Robot archetype registry, with the Go2 as the first driver.
- Teleoperated map building, with map save, versioning, and reload.
- 3D mission editor: waypoint placement on a point cloud, heading control, action attachment.
- Action plugin system — Python files in a directory, auto-discovered, with typed parameters.
- Mission validation and deployment to an edge robot.
- Autonomous mission execution with live monitoring.
- On-robot data capture, with optional sync to S3-compatible storage.
- Safety model: e-stop, geofencing, deadman, preflight validation.

### Explicitly out of scope for v1

- **Multi-robot coordination.** One robot per mission. Fleet *view* is in scope; fleet
  *orchestration* (traffic management, task allocation) is not.
- **Manipulation.** No arm control, no grasping. The action plugin interface is designed not
  to preclude it.
- **Safety certification.** Nothing in this stack is safety-rated. See
  [07_SAFETY.md](07_SAFETY.md) §7.1.
- **Outdoor / GNSS missions.** The frame model supports it; v1 does not implement it.
- **Mission behavior trees.** v1 missions are linear sequences with per-waypoint failure
  policy. The data model reserves room for a tree escape hatch; v1 does not build the editor
  for it.

## 1.5 The core user journey

```
    ┌──────────────┐
    │ Pick archetype│  Go2 · G1 · AMR …
    └──────┬───────┘
           │
     ┌─────┴─────┐
     ▼           ▼
┌─────────┐  ┌─────────┐
│ New map │  │Load map │
│(teleop) │  │(saved)  │
└────┬────┘  └────┬────┘
     └──────┬─────┘
            ▼
    ┌───────────────┐
    │ Build mission │  place waypoints → set heading → attach actions
    └───────┬───────┘
            ▼
    ┌───────────────┐
    │   Validate    │  geofence · reachability · battery · action params
    └───────┬───────┘
            ▼
    ┌───────────────┐
    │    Deploy     │  push to edge robot, verify received
    └───────┬───────┘
            ▼
    ┌───────────────┐
    │    Execute    │  autonomous run, live monitoring, e-stop available
    └───────┬───────┘
            ▼
    ┌───────────────┐
    │    Review     │  captures on-robot → optional cloud sync → analysis
    └───────────────┘
```

Each stage is a screen. See [04_UX_SPEC.md](04_UX_SPEC.md).

## 1.6 Design principles

**Ease of use is the primary metric.** If Nadia cannot add an inspection point in two minutes,
the feature has failed regardless of how powerful it is. Every advanced capability must hide
behind a sensible default. The most important instance of this principle: **waypoint heading
defaults to "face the next waypoint,"** so most operators never think about heading at all.

**Record-then-replay is the authoring gesture.** Every successful product in this space —
Autowalk, ANYbotics, Ghost — has operators drive the robot and capture, then replay. Nobody
authors missions in a text editor. The 3D editor exists to *refine* what was recorded, not to
replace recording.

**The robot is the source of truth, and the UI must never lie about it.** Show the
robot-reported state, not the optimistic local state. Show data age when data is stale. Never
freeze a video frame without marking it frozen. A UI that renders a plausible fiction during a
comms failure is worse than one that goes visibly blank.

**Actions are reusable library entities, not mission children.** An inspection point defined
once is referenced by many missions. This is what makes "how has this asset changed over six
months" answerable. Embedding action definitions inside missions forecloses it permanently.

**Degrade visibly, never silently.** When latency rises, cap the speed and *say so*. When a
capture is dropped, record that it was dropped. Silent truncation reads as success and
destroys trust the first time someone notices.

## 1.7 Glossary

| Term | Definition |
|---|---|
| **Archetype** | A class of robot (Go2, G1, AMR-X). Defines capabilities, kinematics, and safety limits via a capability descriptor. Not an individual robot. |
| **Robot** | A specific physical machine, an instance of an archetype, with an ID, an address, and current state. |
| **Capability descriptor** | The machine-readable declaration of what a robot can measure, what can be adjusted, and what limits are enforced. Implemented as a VDA 5050 `factsheet`. |
| **Driver** | The software owning the connection to one robot. Translates platform-generic commands into vendor protocol, and **enforces safety limits**. |
| **Map** | A versioned 3D representation of a space: point cloud, occupancy grid, pose graph, and origin metadata. |
| **Zone set** | A versioned collection of geofence polygons bound to a map. Immutable; editing produces a new version. |
| **Waypoint** (VDA 5050: *node*) | A pose in the map frame the robot navigates to. Carries position, heading, tolerance, and a list of actions. |
| **Segment** (VDA 5050: *edge*) | The traversal between two waypoints. Carries speed limits and orientation policy. |
| **Action** | A unit of work performed at a waypoint. Provided by a plugin. Has typed parameters and a typed result. |
| **Mission** | An ordered graph of waypoints and segments, plus metadata and failure policy. VDA 5050 calls this an *order*. |
| **Run** | One execution of a mission. Contains run events, which contain captures. |
| **Capture** | A data artifact produced by an action — an image, a measurement, a point cloud. |
| **Base / horizon** | VDA 5050 terms. *Base* is the released portion of a mission the robot is authorized to execute; *horizon* is the planned but unreleased remainder. |
| **Deadman** | A control that must be actively held for teleoperation to proceed. Release means stop. |
| **Cat 0 / Cat 1 / Cat 2** | IEC 60204-1 stop categories. Cat 0 = immediate power removal. Cat 1 = controlled deceleration, then power removal. Cat 2 = controlled stop, power retained. See [07_SAFETY.md](07_SAFETY.md). |
| **MHS** | Anthropic's Model Hardware Standard. An open standard for AI agents operating physical devices, announced 2026-08-27, in research preview. |
| **REP-103 / REP-105** | ROS Enhancement Proposals defining physical units and coordinate frame conventions. Adopted wholesale by this spec. |
| **MCAP** | An indexed container format for heterogeneous timestamped robotics data. The on-robot recording format. |
