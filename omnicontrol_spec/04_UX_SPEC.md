# 04 — User Experience Specification

> Visual tokens, typography, and motion values live in
> [05_DESIGN_SYSTEM.md](05_DESIGN_SYSTEM.md). This document covers structure, screens, and
> interaction behavior.

## 4.1 The structural pattern

Adopt the **tree ↔ viewport ↔ inspector** triad proven by the Rerun viewer. It maps onto this
product exactly:

```
┌───────────────────────────────── status bar (48px, always present) ────────────────┐
│ robot ▾  │ mission name │ BATT 82% · RTT 42ms · LOC 0.91 │      [MISSION STOP][■]  │
├──────┬─────────────────┬──────────────────────────────┬────────────────────────────┤
│      │  WAYPOINTS      │                              │  INSPECTOR                 │
│ tool │  01 ▸ Panel 2A  │        3D VIEWPORT           │  ┌──────────────────────┐  │
│ rail │  02   Corridor  │      (point cloud +          │  │ Waypoint 01          │  │
│      │  03 ▸ Valve B   │       waypoints + robot)     │  │ X 12.42  Y -3.08     │  │
│ 56px │                 │                              │  │ Heading: ⊙ auto      │  │
│      │  320px          │           flex               │  │ ───────────────────  │  │
│      │  resize         │                              │  │ Actions (2)          │  │
│      │                 │                              │  │ 📷 Capture Image  ⋮  │  │
│      │                 │                              │  │ 🌡 Read Sensor    ⋮  │  │
│      │                 │                              │  │ + Add action         │  │
│      │                 │                              │  └──────────────────────┘  │
│      │                 │                              │  360px, resize 320–520     │
└──────┴─────────────────┴──────────────────────────────┴────────────────────────────┘
```

**One selection model, shared.** A single `selectedIds` + `hoveredId` store; the list and the
3D scene are both pure subscribers. Never let each view own its own selection state — that is
where desync bugs and "why is the wrong one highlighted" originate.

## 4.2 Screen inventory

| Screen | Purpose |
|---|---|
| **Fleet** | Robot cards: archetype, state, battery, last run, current mission. Entry point. |
| **Robot detail** | Live telemetry, teleop, sensor feeds, capability descriptor viewer. |
| **Map manager** | Map list, versions, zone-set editor, map build launcher. |
| **Mapping session** | Live teleop mapping with the cloud accumulating in real time. |
| **Mission editor** | The triad above. The core screen. |
| **Preflight** | Validation summary before deploy. |
| **Live run** | Mission executing: map, progress, telemetry HUD, event stream. |
| **Run review** | Completed run: timeline, captures, comparisons. |

## 4.3 Waypoint placement

Model this on the Cities: Skylines road tool, which is the best path-drawing interaction in
any software.

**1. Placement is an explicit mode, entered with `W` or the tool rail.** The cursor becomes a
crosshair, a banner reads `PLACING WAYPOINT · Esc to exit`, and the viewport gains an accent
inset border.

> **Never let a plain click in navigate-mode create geometry.** In a 3D view where the same
> click also orbits the camera, this is the single largest source of "I broke it" in every 3D
> editor ever shipped.

**2. A ghost preview follows the cursor**, at 50% opacity, **with a vertical drop-line to the
ground plane and a ground disc.** The drop-line is not decoration — a floating marker in a
point cloud has no readable depth, and without it operators cannot tell where they are placing.

**3. A live readout is pinned under the cursor**, monospace, on a translucent surface:

```
X 12.42   Y −3.08   Z 0.41  ·  4.2 m from WP-03
```

It turns danger-red with a reason chip when invalid: `NO GROUND`, `IN KEEPOUT`, `OUT OF MAP`,
`UNREACHABLE`.

**4. Picking is two-stage, because raw point-cloud picking is fragile at distance.**

- GPU color-index picking against a downsampled buffer within a 12 px screen-space radius.
- Falling back to intersecting the ray with the fitted ground plane.
- Then **snap to the median Z of the ~30 nearest neighbors.** An operator who clicks a wall
  should not get a waypoint floating 1.5 m in the air.

Highlight candidate points within the pick radius at 1.5× size so the operator sees what will
be hit *before* clicking.

**5. Click commits.** The waypoint scales in over 120 ms, a row appears in the list already
scrolled into view and in rename-edit state, and **the tool stays active** for chain-placing.
`Esc` exits, `Backspace` removes the last placed waypoint, `⌘Z` undoes.

**6. Depth escape hatch:** hold `Shift` while placing to drag the marker vertically along its
drop-line, showing the Z delta numerically. This is Homeworld's move-disc gesture.

**Numeric entry is always available in the inspector as a peer to clicking.** Every 3D tool
that lacks it eventually grows one.

## 4.4 Heading — the highest-leverage design decision

**Heading defaults to `AUTO`: face the next waypoint.** Most operators will never touch it.
This single default does more for ease of use than any other decision in the product.

When an operator does set heading explicitly, the waypoint flips to `LOCKED` and shows a small
lock glyph on its marker.

Three coordinated controls, in order of primacy:

| Control | Role | Why |
|---|---|---|
| **Click a second point** | **Primary.** Immediately after placement, a rubber-band arrow follows the cursor; the next click sets yaw. Live `HDG 137°` on the arrow. | Zero explanation needed — it is how every RTS attack-move works. One continuous gesture: place → aim → done. |
| **Drag-to-rotate ring** | **Secondary.** Appears only when a waypoint is selected. Flat ring on the ground plane with a heading wedge. Snaps to 15°; `Alt` for free rotation. | Familiar from every 3D tool; good for refinement. |
| **Compass dial + numeric field** | **Always present** in the inspector. 96 px compass with N/E/S/W ticks, coupled numeric input, ±1°/±15° steppers, arrow-key nudge. | The accessible, keyboard-reachable, screen-readable path. Non-negotiable. |

> **Explicitly rejected: KSP-style multi-axis handles.** Kerbal Space Program's maneuver node
> is the canonical example of an unlearnable 3D gizmo — the community built the Precise
> Maneuver mod specifically to add numeric entry. A ground robot has one yaw degree of
> freedom; six overlapping handles is a category error.

### The units bug you will otherwise ship

REP-103 yaw is **counter-clockwise positive, zero pointing east**. A compass bearing is **zero
at north, clockwise positive**. These differ by a reflection and a 90° offset.

**Operators see compass degrees, 0–359, N=0. The wire format carries REP-103 radians.**
Convert at exactly one boundary, in one function, with a unit test:

```
compass_deg = (90 − degrees(yaw_rad)) mod 360
```

Never show radians. Never show −180..180.

## 4.5 List ↔ 3D synchronization

- **Hover is symmetric and instant (0 ms).** Hovering a row grows the 3D marker to 1.25× with
  an accent outline. Hovering a marker highlights the row and scrolls it into view **only if
  fully off-screen** — scrolling on hover when partially visible is nauseating.
- **Selection is stronger:** accent fill, a slow pulsing ground ring (the one looping animation
  permitted), and a 2px accent left border on the row. `Shift` for range, `⌘`/`Ctrl` to toggle.
- **Selecting an off-screen waypoint eases the camera to frame it** over 240 ms. Selecting an
  on-screen one never moves the camera.
- **Reordering uses an explicit drag handle**, not whole-row drag, so dragging never fights
  click-to-select. Use `dnd-kit` (MIT, best-in-class keyboard accessibility: Space to lift,
  arrows to move, Space to drop, with live-region announcements). While dragging, **the 3D path
  re-routes live in ghost form** so the operator sees the consequence before dropping.
  `Alt+↑/↓` also works.

> **Renumbering is a real operation, not a cosmetic one.** VDA 5050 derives edge adjacency
> purely from `sequenceId`, and a released base sequence can never be renumbered. The editor
> must therefore treat reordering a *deployed* mission as creating a new mission version, not
> as an in-place edit.

- **The path line is the spine.** An ordered polyline with directional chevrons animating along
  it at a slow constant rate — this is a legend communicating direction, not decoration.
- 3D labels are numbered badges that face the camera, collision-avoid, and degrade to plain
  dots below 12 px apparent size. Never let them overlap into mush.

## 4.6 Actions

Progressive disclosure in three tiers keeps a library of 200 plugin actions from becoming
clutter.

**Tier 1 — the waypoint row shows badges only.** Up to three 16 px filled glyphs, then a `+2`
overflow chip. Zero forms visible.

**Tier 2 — the inspector shows compact one-line cards:**
`[icon] Capture Image · 4K, front cam  [⋮]`. The parameter summary is *generated from the
schema*, not a form. Clicking expands one card inline over 180 ms; only one expands at a time.

**Tier 3 — adding an action opens a ⌘K-style searchable picker**, grouped by category
(Perception / Motion / Comms / Timing / Custom), each entry showing icon, name, one-line
description, and the providing plugin. A `<select>` dies at 15 options; this scales to 200.

### Forms are generated, never hand-written

Each plugin declares typed parameters (§3.7 of [03_CONTRACTS.md](03_CONTRACTS.md)); the UI
renders them. **Plugins never ship UI code.** This is what keeps the surface consistent as the
library grows.

- Show only required and non-default fields. Everything else behind `Advanced (4)`.
- Units are suffix adornments (`2.5` `s`), never in the label.
- Numeric inputs are **drag-scrubbable** — grab the label, drag horizontally. Free once built.
- Validate on blur, not on keystroke. Errors are an inline border plus one line of text, never
  a toast.
- **Every action card has an inline "Test on robot" button.** Being able to fire one action
  without running the whole mission is the difference between a tool people trust and one they
  don't.
- Actions are drag-reorderable within a waypoint and support copy/paste between waypoints — the
  most requested feature in every mission editor ever built.

### Surfacing `RETRIABLE`

VDA 5050 defines a `RETRIABLE` action status and `retry{actionId}` / `skipRetry{actionId}`
instant actions for operator resolution. **Build this affordance.** It converts a failed patrol
into a completed one, and most platforms omit it.

## 4.7 Live run monitoring

- **Robot avatar is an oriented 3D model**, not a dot, with a translucent heading cone (~60°
  FOV) so orientation reads from across a room, and a ground contact disc so it doesn't float.
- **Two distinct paths: planned (accent) and actually traversed (muted breadcrumb).** The delta
  between them is the most information-dense thing on the screen — make it visible.
- **Position interpolates between telemetry ticks** (lerp position, slerp orientation, ~200 ms
  buffer). A robot that teleports at 2 Hz looks broken. Render the raw sample as a faint ghost
  dot so the interpolation isn't lying about the data.
- **Progress in the status bar is segmented per waypoint**, not a smooth bar:
  `WP 4/11 · 02:13 elapsed · ~04:40 remaining`. Segmentation shows *which* leg is slow.
- **Telemetry HUD** is a fixed bottom-left cluster: four large monospace readouts (`BATT`,
  `SPEED`, `HDG`, `RTT`) plus a secondary row. **Fixed positions — a HUD whose items reflow
  cannot be read at a glance.** Every value carries an age indicator when stale beyond 1 s.
- **The event stream is clickable**: clicking an entry flies the camera to where it happened
  and scrubs the timeline there. This is the single most impressive demo moment available.
- **Camera modes** on `1`–`4`: Follow, Top-down, Free, Onboard. Any manual camera input during
  Follow drops to Free with a `RESUME FOLLOW` chip. Never fight the user for the camera.

## 4.8 Safety affordances

### Two stop controls, never confused

This follows directly from [07_SAFETY.md](07_SAFETY.md) §7.3, and getting it wrong is a
liability issue, not a design preference.

| Control | Label | Placement | Behavior |
|---|---|---|---|
| **Mission stop** | `MISSION STOP` | Status bar, left of the e-stop | Cat 2 — controlled hold, motors live, resumable |
| **Emergency stop** | `STOP` + octagon | Status bar, **fixed top-right slot, always present** | Cat 1 settle-then-cut, latched, manual reset |

**E-stop rules:**

- Permanent reserved slot, top-right. Never scrolls, never occluded, never disabled. Top-right
  beats bottom-right because the mouse parks there less often.
- ISO 13850 signature: red actuator on a yellow ring. **These two colors appear nowhere else in
  the application.**
- **Single click fires. No confirmation.** Confirming an emergency stop defeats its purpose.
- **Recovery is the deliberate step:** the app enters a visibly stopped state, and re-arming
  requires `Release E-Stop` followed by a 400 ms hold.
- **Zero hover or press animation.** Dimensionally identical at all times so muscle memory
  works.
- Show the **robot-reported** stop state, with the request state as a separate transient chip
  (`STOP SENT…` → `STOPPED`).
- Global key binding, and support hardware pendants via the Gamepad API.

### Connection loss — three tiers, all instantaneous

| Tier | Trigger | Presentation |
|---|---|---|
| `DEGRADED` | RTT > 200 ms or one missed heartbeat | Amber chip in status bar only |
| `STALE` | 1–5 s | Amber full-width bar; **all write controls disable with explanatory tooltips**; telemetry greys out with ages; video gains a hatch overlay |
| `LOST` | > 5 s | Red bar, video dimmed and hatched, center-viewport card with last-known pose, battery, elapsed, and `Reconnect` |

**Never use a modal for connection loss** — a modal hides the map, which is exactly what the
operator needs to see.

> **Never freeze the last video frame without marking it.** A frozen live frame is the most
> dangerous UI failure in teleoperation. Add a diagonal hatch and `LAST FRAME 3.2s AGO`.

### Deadman

A **persistent, unmissable strip** across the bottom of the video: `HOLD SPACE TO DRIVE` when
idle, becoming a solid green `DRIVING` strip while held. Never a small icon. Auto-releases on
window blur, tab hide, and pointer-leave.

### Preflight, not a dialog

Deploying shows a **summary sheet**: mission name, robot, waypoint count, estimated duration,
the actions that will fire grouped with counts, and a **validation checklist with pass/fail
rows** (battery sufficient, all waypoints reachable, geofence respected, return path clear,
e-stop chain verified, localization confident). Any failing row blocks deploy and links to the
offending item.

Match friction to consequence elsewhere: reversible edits get **no confirmation and always an
undo** (`⌘Z` with a 5 s toast beats a dialog everywhere it is possible). Irreversible actions
against a moving robot get a **400 ms hold-to-confirm** — unfakeable by an accidental click,
and fast enough to use under time pressure, unlike typed-name confirmation.

## 4.9 Teleoperation controls

| Input | Role |
|---|---|
| **WASD + QE + Shift + Space** | Primary on desktop. Show an on-screen key map that lights as keys are pressed. Publish twist at 20 Hz with ~250 ms acceleration ramp. |
| **Gamepad** | The power path. Auto-detect and show a `GAMEPAD CONNECTED` chip. Left stick translate, right stick yaw, RT deadman. Poll at 60 Hz in rAF, send at 20–30 Hz, 0.08 radial deadzone, square-law response. |
| **Virtual joystick** | **Touch/tablet only.** On desktop it is strictly worse than WASD and signals "toy" to enterprise buyers. |

**Latency display is a differentiator when done properly.** Show `RTT 42 ms` in monospace with
a small sparkline of the last 60 samples. **Separate video latency from command RTT and show
both** — they diverge, and conflating them is how operators get surprised.

## 4.10 Mapping session

The map-building screen is teleoperation plus live accumulation.

- The point cloud grows in the viewport as the robot drives. **Voxel-downsample on the edge to
  10–20 cm, cap at 200–500k points, publish at 1–2 Hz — not lidar rate — and send deltas**
  (new voxels only, with a reset event on loop closure). Wire format is a binary typed array or
  int16-quantized tiles, **never JSON**. Render into a `BufferGeometry` mutated in place.
- **Show coverage, not just points.** An operator needs to know which areas are unmapped, so
  render a coverage overlay rather than expecting them to infer it from cloud density.
- **Loop closure is a visible event.** When the pose graph optimizes and the cloud shifts,
  announce it — an unexplained map jump reads as a bug.
- Saving prompts for a name, computes the extrinsics hash, and writes a new map version.

## 4.11 Cross-cutting requirements

**Keyboard.** Every function reachable without a mouse, including heading, reorder, and camera.
A `⌘K` command palette exposing every action with its shortcut — simultaneously the
accessibility story, the power-user story, and the best demo moment in the app.

**Touch.** Trade-show kiosks are touch. One-finger orbit, two-finger pan, pinch zoom, and
**long-press (400 ms) to place a waypoint** — tap is ambiguous with orbit-start. 44×44 px
minimum targets for anything safety-relevant.

**Never put critical information in a hover-only tooltip.** Hover does not exist on touch.

**The 25% test.** Shrink any screenshot to a quarter size. Mission state, robot status, and any
active fault must remain identifiable. If they are not, the demo fails from the aisle.
