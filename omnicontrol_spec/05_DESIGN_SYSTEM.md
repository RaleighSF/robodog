# Appendix D — Design System

> Part of the OmniControl Platform Design Specification.
> This appendix is self-contained: an engineer or designer can implement the entire
> visual layer from this file alone, without reading the rest of the spec.

## D.0 The brief, in one paragraph

Near-black cool-blue chassis with panels lifted by 1px borders and a single inset top
highlight — **chromed by bevel, not by gloss.** Ice-cyan is the only interactive accent;
amber, green, red, gray and violet are reserved strictly for machine state; ISO-13850
red-on-yellow is reserved strictly for the emergency stop. Inter for interface text,
JetBrains Mono with tabular figures for every number that moves, Chakra Petch uppercase
for panel headers — that last one is where the "video game" character lives, and it costs
nothing in enterprise credibility. Everything moves in 120–180 ms on an expo-out curve and
nothing bounces. Telemetry values, status colors, and the e-stop never animate at all.

Structurally the app borrows from four proven sources:

| Source | What we take |
|---|---|
| Rerun viewer | The tree ↔ viewport ↔ inspector triad layout |
| Cities: Skylines road tool | Waypoint path drawing: ghost preview, live readout, Backspace-undo |
| StarCraft II | Fixed command card; sub-50 ms acknowledgement of every operator order |
| Linear | Motion budget, command palette, restraint |

---

## D.1 Color tokens

### Backgrounds and surfaces

A cool blue-black, not a neutral gray. Neutral gray reads as "desktop application";
blue-black reads as "instrument."

| Token | Hex | Use |
|---|---|---|
| `--bg-void` | `#08090B` | App shell, 3D viewport clear color |
| `--bg-base` | `#0B0E12` | Page background |
| `--surface-1` | `#111519` | Panels, cards, sidebars |
| `--surface-2` | `#161B21` | Raised: popovers, hovered rows, input fields |
| `--surface-3` | `#1D242B` | Modals, dropdown menus, floating HUD |
| `--surface-inset` | `#0A0D10` | Wells: log stream, timeline track, code |

We deliberately avoid pure `#000000` for large fields — it mirrors the room under booth
lighting.

### Borders

| Token | Value | Use |
|---|---|---|
| `--border-subtle` | `#1E262E` | In-panel dividers, table row rules |
| `--border` | `#2C363F` | Panel outlines, default input borders |
| `--border-strong` | `#4A5A68` | Hovered/focused input, active panel outline |
| `--bevel-top` | `rgba(255,255,255,0.06)` | 1px inset top highlight — this *is* the chrome |

### Text

Contrast ratios below are computed with the WCAG relative-luminance formula and verified.

| Token | Hex | On `--surface-1` | On `--surface-3` |
|---|---|---|---|
| `--text-primary` | `#E6EDF3` | 15.52:1 | 13.27:1 |
| `--text-secondary` | `#9FB0C0` | 8.25:1 | 7.05:1 |
| `--text-tertiary` | `#8494A3` | 5.90:1 | 5.04:1 |

`--text-tertiary` is set at `#8494A3` rather than a darker gray specifically so it clears
4.5:1 on *every* surface including `--surface-3`. Do not darken it.

### Accent and semantic state

| Token | Hex | On `--bg-base` | On `--surface-3` | Meaning |
|---|---|---|---|---|
| `--accent` | `#3DD3F0` | 10.84:1 | 8.79:1 | Primary action, selection, focus |
| `--accent-press` | `#22B4D1` | — | — | Active/pressed |
| `--status-ok` | `#3FD68C` | 10.32:1 | 8.37:1 | Nominal, connected, complete |
| `--status-warn` | `#FFB224` | 10.73:1 | 8.69:1 | Degraded, low battery, high latency |
| `--status-danger` | `#FF5C5C` | 6.39:1 | 5.18:1 | Fault, comms lost |
| `--status-offline` | `#8494A3` | 6.21:1 | 5.04:1 | Unknown / no data |
| `--mission-active` | `#B39DFF` | 8.46:1 | 6.86:1 | Mission executing under autonomy |

Solid-fill foregrounds, verified:

- `#0B0E12` on `--accent` → **10.84:1**
- `#0B0E12` on `--status-warn` → **10.73:1** (never white on amber)
- `#FFFFFF` on `--estop-red` → **5.02:1**
- Focus ring `#7DF0FF` on `--surface-2` → **13.01:1**

**Why cyan and not amber as the primary accent.** Amber is the industrial-brand instinct
(Boston Dynamics, Caterpillar, Fanuc) but it collides irreconcilably with the warning
state. Amber must mean *warning* and nothing else. Cyan on near-black is also the
Homeworld/instrument-console signature that satisfies the "video game" half of the brief.
Brand amber belongs in the logo lockup and the mission-active badge chrome, never in
interactive controls.

**`--status-offline` must be gray, never dark red.** Unknown is not the same as bad, and
conflating them trains operators to ignore red.

### Emergency stop — a reserved palette

| Token | Hex |
|---|---|
| `--estop-red` | `#D42B2B` |
| `--estop-amber` | `#F5C518` |

ISO 13850 specifies a red actuator on a yellow background and reserves that combination
exclusively for emergency stop. Carrying the convention into software is what makes the
affordance instantly legible to a plant-floor buyer. **These two tokens appear nowhere
else in the application.**

### Bright-environment mode

Booth lighting runs 500–2000 lux against a screen doing roughly 300 nits. Ambient
reflection adds a *constant* luminance floor that annihilates the distinction between
`#000` and `#1A1A1A`. A dark UI tuned in an office is unreadable from the aisle.

Ship a `data-env="bright"` variant that:

1. Lifts `--bg-base` to `#12171D` and `--surface-1` to `#1C232B`. Raising the black point
   beats raising text brightness, because the glare floor is additive.
2. Raises all borders one step (`--border` → `#3A4753`).
3. Boosts semantic chroma: ok `#4EE89B`, warn `#FFC24D`, danger `#FF7B7B`.
4. Increases base font size 13 → 14px and status-dot diameter 8 → 10px.

Target ≥7:1 (WCAG AAA) for primary text in this mode. **Put the toggle in the top bar, not
in a settings page** — someone will need it thirty seconds before a demo.

---

## D.2 Typography

All three families are on Google Fonts under the SIL Open Font License.

**Interface text — `Inter`.** Variable, broad language coverage, designed for screens at
small sizes. Enable `font-feature-settings: "cv05" 1, "ss03" 1;` and turn on `zero`
wherever digits appear inline.

**Numeric telemetry — `JetBrains Mono`.** Chosen over the alternatives for the tallest
x-height among the free monospaces (best at 11–13px), a slashed zero by default, and
clearly differentiated `1/l/I` and `5/S` — which matters when someone reads a battery
percentage from across a room. Use it for every number that changes, all IDs, timestamps,
and log output.

> **Always set `font-variant-numeric: tabular-nums;` on telemetry.** This is the single
> highest-impact typographic decision in the application. Without it, readouts jitter
> horizontally on every update and the whole UI reads as unstable.

`IBM Plex Mono` (what Foxglove uses) is an acceptable substitute with slightly more
editorial warmth. Pick one, never both.

**Display and panel labels — `Chakra Petch`.** A squared sans with tapered corners that
reads as technical HUD without tipping into novelty. Use it *only* for panel header
labels, section eyebrows, and the mission-name display: uppercase, `letter-spacing:
0.08em`, 11–12px, `--text-secondary`.

Acceptable substitutes if Chakra Petch reads too gamey for a given room: `Archivo` or
`Saira`. **Avoid `Orbitron` and `Rajdhani`** — they read as sci-fi cosplay to industrial
buyers and will undermine the credibility the rest of the palette earns.

### Type scale

| Role | Family | Size | Line height | Weight | Tracking |
|---|---|---|---|---|---|
| Display (mission name) | Chakra Petch | 20 | 26 | 600 | 0 |
| Panel header | Chakra Petch | 11 | 14 | 600 | +0.08em, UPPER |
| Body / list | Inter | 13 | 18 | 450 | 0 |
| Body strong | Inter | 13 | 18 | 600 | 0 |
| Meta / helper | Inter | 12 | 16 | 450 | 0 |
| Form label | Inter | 11 | 14 | 600 | +0.04em, UPPER |
| Telemetry large | JetBrains Mono | 28 | 32 | 500 | −0.01em, tnum |
| Telemetry inline | JetBrains Mono | 12 | 16 | 500 | 0, tnum |
| Log / stream | JetBrains Mono | 11 | 16 | 400 | 0 |

13px body is deliberate. It is the workhorse size in Linear and Foxglove, and it is what
makes a dense application feel professional rather than oversized. Shift the entire scale
+1px in bright mode.

---

## D.3 Space, radius, elevation

**Spacing** — 4px base, but only ever use `4 / 8 / 12 / 16 / 24 / 32 / 48`. Panel padding
16, card padding 12, list-row vertical padding 8, icon-to-label gap 8, form field rhythm
12, section gap 24.

**Grid** — this is not a document, so there is no 12-column grid. The app shell is a fixed
region layout:

```
┌──────────────────────────────────────────────── 48px status bar ─────────────┐
├──────┬──────────────┬─────────────────────────────────┬──────────────────────┤
│ rail │   context    │                                 │      inspector       │
│ 56px │   320px      │           viewport              │       360px          │
│fixed │ resize       │            flex                 │   resize 320–520     │
│      │ 280–480      │                                 │                      │
├──────┴──────────────┴─────────────────────────────────┴──────────────────────┤
└────────────────────── 200px timeline drawer (optional) ──────────────────────┘
```

Collapse the inspector to an overlay below 1280px viewport width. Design primarily for
1920×1080 (trade-show monitors), secondarily for 2560×1440.

**Radius** — `2` chips and tags, `4` buttons/inputs/rows, `6` cards and panels, `10`
modals and floating HUD, `999` avatars, joystick knob, e-stop. **Nothing above 10 on a
structural surface.** Large radii read as consumer mobile and destroy industrial
credibility instantly.

**Elevation — borders first, shadows last.** This is the main thing separating good dark UI
from bad. Shadows barely read on dark backgrounds; raising surface lightness per elevation
level is the reliable mechanism.

| Level | Surface | Border | Shadow |
|---|---|---|---|
| 0 — page | `--bg-base` | none | none |
| 1 — panel | `--surface-1` | 1px `--border` | none |
| 2 — raised / input | `--surface-2` | 1px `--border` | none |
| 3 — popover | `--surface-3` | 1px `--border-strong` | `0 8px 24px rgba(0,0,0,.5)` |
| 4 — modal / HUD | `--surface-3` | 1px `--border-strong` | `0 16px 48px rgba(0,0,0,.65)` |

### The chrome treatment

Apply to panels and primary buttons only:

```css
background: linear-gradient(180deg, #161B21 0%, #111519 100%);
box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
border: 1px solid #2C363F;
```

A 1px inset top highlight against a subtle vertical gradient is the entire chromed-metal
effect. **Resist adding glow.** The one legitimate use of glow is a 0–2px outer `--accent`
bloom on the *selected* 3D entity and on the active mission path — in a 3D scene, glow is
a depth cue rather than decoration.

**Focus** — `outline: 2px solid #7DF0FF; outline-offset: 2px;` on everything, never
removed.

---

## D.4 Iconography

| Library | Count | License | Status (2026) | Verdict |
|---|---|---|---|---|
| **Lucide** | 1,500+ | ISC | Actively maintained, weekly releases | **Primary.** Consistent 24×24 / 2px stroke grid, tree-shakes, covers the needed vocabulary (`radio-tower`, `battery`, `cpu`, `route`, `crosshair`, `map-pin`, `gauge`, `wifi-off`, `octagon-x`, `waypoints`). Use `stroke-width: 1.75` at 16px for a finer instrument feel. |
| **Material Symbols** | 3,700+ | Apache 2.0 | Google, actively maintained | **Gap-filler only.** Best coverage of genuinely industrial glyphs (`precision_manufacturing`, `conveyor_belt`, `robot_2`, `sensors`, `emergency_home`). Optical style differs from Lucide — normalize stroke weight and never mix within a single row. |
| **Phosphor** | 1,200+ | MIT | Actively maintained | Acceptable secondary for *filled* status glyphs, since Lucide is stroke-only. |
| **Tabler** | 5,900+ | MIT | Actively maintained | Viable Lucide alternative with wider coverage. Pick one or the other, never both. |

**Recommendation: Lucide as the system, Material Symbols (Rounded, weight 300, fill 0) for
the roughly fifteen robotics-specific glyphs Lucide lacks.** Ship both as subset local
assets — never hotlink Google's icon font in a booth with unreliable wifi.

For **map and 3D markers, use no icon library at all.** Draw waypoint markers as
SVG/canvas primitives you control (numbered chevron pin, heading wedge, action badge) so
they scale correctly with camera distance and depth.

---

## D.5 Motion

### Durations — use exactly these five

| Token | Duration | Applies to |
|---|---|---|
| `instant` | 0 ms | Any state change driven by telemetry |
| `fast` | 120 ms | Hover, focus, button press, tooltip, selection highlight |
| `base` | 180 ms | Dropdowns, popovers, panel expand/collapse, list reorder |
| `slow` | 240 ms | Modal/drawer enter, 3D camera fly-to |
| `deliberate` | 400 ms | Hold-to-confirm gestures and e-stop re-arming *only* |

### Easing

| Case | Curve | Duration |
|---|---|---|
| Enter (appearing) | `cubic-bezier(0.16, 1, 0.3, 1)` | 120–180 ms |
| Exit | `cubic-bezier(0.4, 0, 1, 1)` | 100 ms |
| Move / resize / reorder | `cubic-bezier(0.2, 0, 0, 1)` | 180 ms |
| 3D camera | `cubic-bezier(0.33, 0, 0.15, 1)` | 240–400 ms |

Exits are always faster than entrances. The camera always eases and **never cuts** — a
hard cut destroys spatial orientation. **No bounce or overshoot anywhere;** springy motion
reads as "toy" to industrial buyers.

### What must animate

- **Selection linking** between list and 3D: 120 ms highlight crossfade, plus a 240 ms
  camera ease if the selected waypoint is off-screen.
- **Waypoint reorder**: FLIP animation at 180 ms.
- **Robot avatar position**: interpolate between telemetry ticks (lerp position, slerp
  orientation, ~200 ms buffer). A robot that teleports at 2 Hz looks broken; a smoothly
  interpolated one looks premium. Render the raw sample as a faint ghost dot so the
  interpolation is not lying about the data.
- **Path progress**: the completed segment fills with `--accent` over 180 ms.

### What must never animate

These are safety requirements, not preferences.

1. **Numeric telemetry values.** No count-up or roll animations, ever. A number that is
   animating is a number that is *wrong* for 300 ms. Snap.
2. **Status color changes.** An ok → danger transition must be instantaneous. Never
   crossfade a fault into view.
3. **The e-stop button.** No hover scale, no ripple, no transition. It must be
   dimensionally identical at all times so muscle memory works.
4. **Connection-loss indication.** Appears on the same frame the heartbeat is missed.
5. **Anything that delays acknowledgement of an operator command.** Acknowledge in ≤50 ms
   with an optimistic local state change, then reconcile with the server.
6. **No loading skeletons on live telemetry panels.** Show the last-known value with an
   explicit staleness age (`BATT 74% · 3.2s ago`). A skeleton on live data implies "no
   robot," which is a lie.

Respect `prefers-reduced-motion` by dropping everything to 0 ms — except the 3D camera
ease, which is an orientation aid rather than decoration and should be reduced to 120 ms
rather than removed.

---

## D.6 Status encoding — never hue alone

Roughly 8% of men have red-green color vision deficiency, and a plant floor is a
male-skewed audience. Every status uses a **triple**: shape carries the meaning, color
accelerates it, and the text label is ground truth.

| Status | Color | Shape | Label |
|---|---|---|---|
| OK / nominal | `--status-ok` | Filled **circle** | `OK` |
| Warning | `--status-warn` | Filled **triangle** | `WARN` |
| Danger / fault | `--status-danger` | Filled **octagon** | `FAULT` |
| Offline / unknown | `--status-offline` | Hollow **circle**, dashed | `OFFLINE` |
| Active mission | `--mission-active` | Filled **diamond** | `RUNNING` |

The text label is **always visible, never hover-only.** The ok/danger pair also differs
strongly in luminance (10.32:1 versus 6.39:1 on base), so the two remain distinguishable
in a fully monochrome render — verify any palette change against a grayscale
screenshot. Paths and chart series additionally carry dash patterns.

---

## D.7 Physical realities

### Viewing distance

Booth audiences read from 2–4 m; control-room operators from 0.6 m. Design **the status
bar and telemetry HUD for 3 m** (28px+ mono numerals, 10px status dots, high chroma) and
everything else for 0.6 m.

> **The 25% test.** Shrink a screenshot to a quarter size. Mission state, robot status,
> and any active fault must still be identifiable. If they are not, the demo will fail
> from the aisle.

### Touch and mouse

Assume both — trade-show kiosks are touch, control rooms are mouse and keyboard.

- Minimum hit target **44×44 px** for anything safety-relevant (e-stop, deadman, deploy),
  even when the visual is smaller. Expand hit areas with padding or pseudo-elements rather
  than growing the visual.
- **Never put critical information in a hover-only tooltip.** Hover does not exist on
  touch. Tooltips supplement; they never carry the only copy of a fact.
- 3D needs explicit touch equivalents: one-finger orbit, two-finger pan, pinch zoom, and
  **long-press (400 ms) to place a waypoint** — tap is ambiguous with orbit-start.
- Right-click context menus always need a long-press equivalent and a visible `⋮` overflow
  button.

### Keyboard and screen reader

- Every function reachable without a mouse, including heading (compass field plus arrow
  keys), waypoint reorder (`Alt+↑/↓`), and camera (`1–4`).
- A `⌘K` command palette exposing every action with its shortcut. This is simultaneously
  the accessibility story, the power-user story, and the best demo moment in the app.
- `aria-live="polite"` for mission progress; `aria-live="assertive"` for faults, e-stop,
  and link loss.
- The 3D canvas gets an adjacent visually-hidden text mirror of scene state (waypoint list
  with coordinates and headings) so it is not an accessibility void.
- Focus always visible, trapped in modals, restored on close. Support 200% browser zoom
  without horizontal scroll in the panel regions.

---

## D.8 Reference implementations worth studying

| Product | What to take from it |
|---|---|
| [Foxglove Studio](https://github.com/foxglove/studio) | Panel docking with blue drop-target overlay; monospace topic/telemetry readouts; IDE-grade density |
| [Rerun](https://rerun.io/docs/getting-started/navigating-the-viewer) | Blueprint tree / viewport / selection panel / timeline four-region layout |
| [Boston Dynamics Orbit](https://dev.bostondynamics.com/docs/concepts/orbit/about_orbit.html) | Restraint: one accent, one surface, hairline dividers, almost no motion |
| [Linear](https://linear.app) | Motion budget (100–160 ms expo-out), command palette, keyboard-first |
| Cities: Skylines road tool | Ghost preview, live length/angle readout, snap indicators, Backspace-undo |
| Homeworld | Move disc: click for ground position, drag vertically for altitude |
| StarCraft II | Fixed command card; instant order acknowledgement |

**Explicitly rejected:** Kerbal Space Program's maneuver-node gizmo. It is the canonical
example of an unlearnable multi-handle 3D control — the community built the Precise
Maneuver mod specifically to add numeric entry. See §3 of the main spec for the heading
control we use instead.
