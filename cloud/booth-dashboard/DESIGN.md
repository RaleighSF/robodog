---
name: Watch Dog Overwatch (booth dashboard)
description: EICAS glass cockpit for a live Unitree Go2 - Azimuth chassis with a swappable cloud accent.
colors:
  bg-void: "#08090B"
  bg-base: "#0B0E12"
  surface-1: "#111519"
  surface-2: "#161B21"
  surface-3: "#1D242B"
  surface-inset: "#0A0D10"
  border-subtle: "#1E262E"
  border: "#2C363F"
  border-strong: "#4A5A68"
  bevel-top: "rgba(255, 255, 255, 0.06)"
  text-primary: "#E6EDF3"
  text-secondary: "#9FB0C0"
  text-tertiary: "#8494A3"
  status-ok: "#3FD68C"
  status-warn: "#FFB224"
  status-danger: "#FF5C5C"
  status-offline: "#8494A3"
  warning-text: "#FF8A8A"
  danger-ink: "#1A0505"
  focus: "#7DF0FF"
  accent-azure: "#3A9BF0"
  accent-azure-press: "#1F86E0"
  accent-azure-ink: "#06121F"
  accent-aws: "#FF9F1C"
  accent-aws-press: "#E8890A"
  accent-aws-ink: "#1A0F00"
  adi-sky: "#13283F"
  adi-ground: "#2A2118"
  nvidia-green: "#76B900"
  go2-black: "#1B2128"
  go2-white: "#C9D3DD"
  go2-gray: "#5F6D7B"
  go2-metal: "#9AA7B4"
typography:
  display:
    fontFamily: "Chakra Petch, IBM Plex Sans, sans-serif"
    fontSize: "calc(var(--u) * 2.1)"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.06em"
  annunciator:
    fontFamily: "Chakra Petch, IBM Plex Sans, sans-serif"
    fontSize: "calc(var(--u) * 1.6)"
    fontWeight: 700
    lineHeight: 1.05
    letterSpacing: "0.08em"
  readout-dial:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "calc(var(--u) * 2.25)"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0"
    fontFeature: "tnum"
  readout:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "calc(var(--u) * 2.05)"
    fontWeight: 700
    lineHeight: 1.05
    letterSpacing: "0"
    fontFeature: "tnum"
  headline:
    fontFamily: "IBM Plex Sans, system-ui, -apple-system, sans-serif"
    fontSize: "calc(var(--u) * 2.05)"
    fontWeight: 400
    lineHeight: 1.28
  body:
    fontFamily: "IBM Plex Sans, system-ui, -apple-system, sans-serif"
    fontSize: "calc(var(--u) * 1.45)"
    fontWeight: 400
    lineHeight: 1.35
  data:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "calc(var(--u) * 1.35)"
    fontWeight: 400
    lineHeight: 1.35
    letterSpacing: "0"
    fontFeature: "tnum"
  title:
    fontFamily: "Chakra Petch, IBM Plex Sans, sans-serif"
    fontSize: "calc(var(--u) * 1.2)"
    fontWeight: 600
    letterSpacing: "0.08em"
  severity-tag:
    fontFamily: "Chakra Petch, IBM Plex Sans, sans-serif"
    fontSize: "calc(var(--u) * 1.35)"
    fontWeight: 700
    letterSpacing: "0.08em"
  fine:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
    fontSize: "calc(var(--u) * 0.95)"
    fontWeight: 400
    lineHeight: 1.35
rounded:
  hair: "1px"
  chip: "2px"
  ctl: "4px"
  panel: "6px"
spacing:
  u: "clamp(9px, 0.62vw, 24px)"
  xxs: "calc(var(--u) * 0.3)"
  xs: "calc(var(--u) * 0.4)"
  sm: "calc(var(--u) * 0.6)"
  md: "calc(var(--u) * 0.8)"
  lg: "calc(var(--u) * 1)"
  xl: "calc(var(--u) * 1.2)"
  xxl: "calc(var(--u) * 2)"
components:
  panel:
    backgroundColor: "{colors.surface-1}"
    rounded: "{rounded.panel}"
  well:
    backgroundColor: "{colors.surface-inset}"
    rounded: "{rounded.ctl}"
  page-key:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.text-secondary}"
    typography: "{typography.title}"
    rounded: "{rounded.chip}"
    padding: "calc(var(--u) * 0.32) calc(var(--u) * 0.9)"
  page-key-on:
    backgroundColor: "{colors.accent-azure}"
    textColor: "{colors.accent-azure-ink}"
    rounded: "{rounded.chip}"
  annunciator-off:
    backgroundColor: "{colors.surface-inset}"
    textColor: "{colors.text-tertiary}"
    typography: "{typography.annunciator}"
    rounded: "{rounded.ctl}"
    padding: "calc(var(--u) * 0.45) calc(var(--u) * 1)"
  annunciator-warning-lit:
    backgroundColor: "{colors.status-danger}"
    textColor: "{colors.danger-ink}"
    rounded: "{rounded.ctl}"
  annunciator-caution-lit:
    backgroundColor: "{colors.status-warn}"
    textColor: "{colors.bg-base}"
    rounded: "{rounded.ctl}"
  severity-warning:
    backgroundColor: "{colors.status-danger}"
    textColor: "{colors.danger-ink}"
    typography: "{typography.severity-tag}"
    rounded: "{rounded.chip}"
  severity-caution:
    backgroundColor: "{colors.status-warn}"
    textColor: "{colors.bg-base}"
    typography: "{typography.severity-tag}"
    rounded: "{rounded.chip}"
  severity-advisory:
    textColor: "{colors.accent-azure}"
    typography: "{typography.severity-tag}"
    rounded: "{rounded.chip}"
  cas-message:
    backgroundColor: "{colors.surface-2}"
    typography: "{typography.headline}"
    rounded: "{rounded.ctl}"
    padding: "calc(var(--u) * 0.6) calc(var(--u) * 0.8)"
  readout-cell:
    backgroundColor: "{colors.surface-inset}"
    typography: "{typography.readout}"
    rounded: "{rounded.ctl}"
    padding: "calc(var(--u) * 0.5) calc(var(--u) * 0.7)"
  freshness-lamp:
    backgroundColor: "{colors.surface-inset}"
    textColor: "{colors.status-ok}"
    rounded: "{rounded.ctl}"
    padding: "calc(var(--u) * 0.5) calc(var(--u) * 0.9)"
  freshness-lamp-stale:
    backgroundColor: "{colors.surface-inset}"
    textColor: "{colors.status-warn}"
    rounded: "{rounded.ctl}"
  ask-input:
    backgroundColor: "{colors.surface-2}"
    textColor: "{colors.text-primary}"
    typography: "{typography.body}"
    rounded: "{rounded.ctl}"
    padding: "calc(var(--u) * 0.5) calc(var(--u) * 0.8)"
---

# Design System: Watch Dog Overwatch (booth dashboard)

## Overview

**Creative North Star: "The Flown Dog"**

The robot is flown, not charted. The screen is an EICAS glass cockpit (engine-indicating and crew-alerting system) rather than a KPI-tile dashboard: each of the Go2's twelve joint motors reads like an engine dial, the agent overwatch speaks through a crew-alerting stack, and every other system lives on a synoptic page that staff page through or that cycles by itself in booth mode. It is built to be read from about 3 m in a few seconds, and to reward a closer look at arm's length.

The chassis comes from Azimuth (`/Users/Raleigh/Development/azimuth/DESIGN.md`): near-black, cool-blue panels lifted by 1px borders and one inset top bevel, with no glow, gradient or glass. On top of it the booth adds two things. The first is EICAS cockpit grammar: master annunciators, severity-ranked messages, invalid-data dashes and green/amber/red dial arcs. The second is a **cloud accent** that is swapped at build time: Azure blue for Microsoft Ignite, AWS orange for re:Invent. Everything except the accent is shared between the two shows.

The whole cockpit is sized from one viewport unit, `--u` (`spacing.u`, about 11.9px on a 1920 screen), so a 1080p booth screen and a 4K one look the same from the aisle.

**Key Characteristics:**
- Near-black tonal panels; depth comes from 1px borders and a single 6% white top bevel.
- Status colours have fixed EICAS meanings: green nominal, amber caution, red warning, grey unknown.
- One cloud accent (Azure or AWS), used only for advisories, the selected page key, the attitude pointer and the brand word.
- Three typefaces with strict jobs: Chakra Petch uppercase for titles and alerts, IBM Plex Sans for sentences, JetBrains Mono tabular figures for every number.
- Instruments are drawn as inline SVG from data. There is no chart library and there are no pictorial icons.
- A live 3D Go2 is the hero. Its joint housings take on the status colour.

## Colors

The palette is a cold, almost-black instrument panel. Saturated colour appears only when a status or the cloud accent calls for it.

### Primary (cloud accent, swapped per show)
- **Azure Signal Blue** (`accent-azure`): the Ignite accent. It is Azure's #0078D4 lifted for a dark chassis and passes AA on surface-1. Used for the ADVISORY tag and its outline, the selected synoptic page key, the page-cycle progress bar, the attitude-ring pointer, the word "OVERWATCH" in the title, and text selection. Its press tone (`accent-azure-press`) and ink (`accent-azure-ink`, for text on a filled accent) travel with it.
- **AWS Smile Orange** (`accent-aws`): the re:Invent accent, with `accent-aws-press` and `accent-aws-ink`. It fills exactly the same roles.

### Tertiary (fixed status semantics)
- **Nominal Green** (`status-ok`): live lamp, nominal dial arc (at 55% opacity), nominal needle, cell bars and the runtime-budget segments that are lit, foot contact, "OK" command results.
- **Caution Amber** (`status-warn`): caution severity, the lit MASTER CAUTION, the dial caution band (at 75% opacity), caution needles and readouts, the stale lamp, the SYNTHETIC DATA tag, every invalid-data dash, ATT FAIL, and the ADI aircraft symbol.
- **Warning Red** (`status-danger`): warning severity, the lit MASTER WARNING, the dial redline, warning needles, readouts filled red, failed commands, and dashed limit lines on trend tapes.
- **Warning Message Red** (`warning-text`): a lighter red used only for the sentence text of a WARNING message, so a long sentence stays readable on surface-2.
- **Danger Ink** (`danger-ink`): text on any red fill. Text on any amber fill is `bg-base`, never white.
- **Unknown Grey** (`status-offline`): unknown or no-data status. It is the same value as text-tertiary, and it is never a dark red.

### Neutral
- **Void** (`bg-void`): the html background behind the cockpit.
- **Base** (`bg-base`): the cockpit grid background.
- **Panel** (`surface-1`): panels, the top strip, the strip under the body.
- **Raised** (`surface-2`): crew-alerting messages, page keys, the ask input.
- **Hub** (`surface-3`): the dial hub cap. Nothing else uses it.
- **Well** (`surface-inset`): the 3D stage, readout cells, annunciators that are off, the freshness lamp, dial readout boxes, trend-tape plots.
- **Hairline / Border / Strong border** (`border-subtle`, `border`, `border-strong`): in-panel dividers, then panel outlines, then hover state, dial ticks and the attitude bank scale.
- **Bevel** (`bevel-top`): the 1px inset top highlight. This bevel is the only chrome.
- **Text ladder** (`text-primary`, `text-secondary`, `text-tertiary`): values and sentences; titles and labels; units, timestamps, scales and legal text. Tertiary already clears 4.5:1, so do not darken it.
- **ADI sky and ground** (`adi-sky`, `adi-ground`): used only inside the ATTITUDE page's attitude indicator.
- **Go2 materials** (`go2-black`, `go2-white`, `go2-gray`, `go2-metal`): the three.js material colours for the 3D dog. The scene uses ACES filmic tone mapping, a hemisphere light (#E8EEF4 sky, #0B0E12 ground), a white key light and a #D6E2EE rim light.
- **NVIDIA Green** (`nvidia-green`): the "NVIDIA" wordmark text only.

### Named Rules
**The Cloud Swap Rule.** The cloud brand lives only in `src/lib/theme.ts` and is chosen at build time with `NEXT_PUBLIC_THEME=aws|azure` (Azure is the default). `layout.tsx` writes `--accent`, `--accent-press` and `--accent-ink` onto `<html>`, and the "Built on …" text comes from the same theme. Components may only reference `var(--accent*)`. They never use an accent hex and never name a cloud in their copy.

**The Fixed Semantics Rule.** Green, amber, red and grey mean nominal, caution, warning and unknown on every surface, including the 3D dog. The accent is never a status. Red appears only for a real warning.

**The One Accent Rule.** At any moment only one cloud accent is on screen, and it marks advisory, selection and pointer roles only. Do not use it for decoration.

## Typography

**Display / Title Font:** Chakra Petch (500/600/700), falling back to IBM Plex Sans
**Body Font:** IBM Plex Sans (400/500/600), falling back to system-ui
**Numeric Font:** JetBrains Mono (400/500/700) with `tabular-nums`

All three are self-hosted by `next/font` (variables `--font-chakra`, `--font-plex`, `--font-mono`), so the booth needs no font CDN.

**Character:** Chakra Petch gives the squared, stencilled voice of avionics placards. Plex keeps the agent's sentences calm and human. Mono figures hold still while values change.

### Hierarchy
All sizes are multiples of `--u`. The pixel values below are at 1920 px wide.
- **Display** (Chakra 700, 2.1u ≈ 25px, uppercase): the product title "WATCH DOG OVERWATCH" only.
- **Annunciator** (Chakra 700, 1.6u ≈ 19px, uppercase, 0.08em): the words MASTER WARNING and MASTER CAUTION. "MASTER" above them is a 0.9u title.
- **Readout, dial** (Mono 700, 2.25u ≈ 27px): joint temperature in the box under each needle. The unit is set at 0.55em in tertiary.
- **Readout** (Mono 700, 2.05u ≈ 24px): synoptic readout cells. The unit is set at 0.5em, weight 500, in tertiary. Posture is shown at 2.3u.
- **Headline** (Plex 400, 2.05u ≈ 24px, 1.28, max 60ch, `text-wrap: pretty`): the agent's sentence in each crew-alerting message. This is the line that makes passers-by stop.
- **Body** (Plex 400, 1.45u ≈ 17px, 1.35): default interface text.
- **Data** (Mono 400, 1.35u): message metadata such as the cited metric and the time, status values, and timestamps.
- **Title** (Chakra 600, 1.2u ≈ 14px, uppercase, 0.08em, text-secondary): every panel, readout and instrument label. Inside cells it drops to 0.95–1.05u.
- **Severity tag** (Chakra 700, 1.35u, 0.08em): WARNING, CAUTION, ADVISORY.
- **Fine** (Plex 400, 0.95u ≈ 11px, tertiary): the legal footer, dial scales and budget scales.

### Named Rules
**The Mono Number Rule.** Every number that changes, every ID, every timestamp and every unit-bearing value is set in JetBrains Mono with tabular figures. Any text with digits in it gets the `.num` class.

**The Placard Rule.** Chakra Petch is always uppercase, always tracked (0.06–0.08em), and never used for sentences.

## Layout

**Booth (wider than 900px):** a full-viewport grid with no page scroll (`body { overflow: hidden }`). Padding is 1.2u and gaps are 1u. Columns are 1.62fr and 1fr, which gives roughly 62% to the body and 38% to the crew-alerting stack. Rows, from top:
1. **Top strip** (auto height): NTT DATA mark, then the identity block (title plus "UNITREE GO2 · device id" in mono), then the two master annunciators pushed right, then the freshness lamp, then the brand marks ("Built on …", "Powered by NVIDIA").
2. **Body and crew-alerting stack** (`minmax(0, 1fr)`): on the left, the 3D stage inside the attitude ring, with four translucent leg quadrants in the corners. Screen placement follows the camera: FR top-left, RR top-right, FL bottom-left, RL bottom-right. Each quadrant holds three joint dials (hip, thigh, calf). On the right, the crew-alerting list scrolls inside its panel. Below it are pinned the monitored-systems status list (two columns) and the posture and runtime-budget strip, which never cycle away.
3. **Synoptic band** (fixed at 17.5u, full width): a vertical column of page keys on the left (POWER, GAIT, ATTITUDE, VISION, EDGE, LINK), with the page itself to the right. Each page is a short horizontal grid of readout cells, trend tapes and SVG instruments.
4. **Ask** (staff mode only, auto height): label, input and note.
5. **Legal footer** (auto height).

**Modes:** `?mode=booth` (the default) runs unattended. Page keys are disabled and the page cycles every 12 s. `?mode=staff` enables the page keys, lets staff acknowledge annunciators, and shows the Ask row.

**Phone and tablet (900px and narrower):** everything stacks in one column (strip, body, crew alerting, synoptic, ask, legal), the page scrolls, and `--u` is fixed at 9px. The 3D stage becomes a 78vw-tall block, and the leg quadrants flow below it as solid panels, each with a three-column dial grid at 72px. Page keys wrap into a row and the cycle bar is hidden. Readout grids collapse to one column of label/value rows, with values at 18px.

**Spacing rhythm:** spacing is set in `--u` multiples (`spacing.*`, mostly 0.3, 0.4, 0.6, 0.8, 1, 1.2 and 2u). The Azimuth pixel steps `--s1…--s7` (4–48px) are declared in the stylesheet but nothing uses them.

## Elevation & Depth

The cockpit is flat and tonal. Depth comes from stepping up surface lightness (inset well, then panel, then raised) and from 1px borders. The only shadows are inset.

### Shadow Vocabulary
- **Panel bevel** (`box-shadow: inset 0 1px 0 rgba(255,255,255,0.06)`): every panel and the top strip.
- **Key cap** (`box-shadow: inset 0 1px 0 rgba(255,255,255,0.06), inset 0 -2px 0 rgba(0,0,0,0.35)`): synoptic page keys, so they read as physical keys. The selected key keeps only `inset 0 -2px 0 rgba(0,0,0,0.25)`.

### Named Rules
**The No-Glow Rule.** There is no outer shadow, glow, gradient, blur or glass anywhere. Translucency is used once: leg quadrants are `surface-1` at 45% over the 3D stage, with a 70% border.

## Shapes

The language is small and square, like avionics. Radii are 6px on panels and leg quadrants, 4px on controls (annunciators, lamp, messages, readout cells, inputs, tape plots), 2px on chips (severity tags, SYNTHETIC tag, page keys, dial readout boxes), and 1px on bar segments. Nothing is larger than 6px. The only circles are instruments: dials, the attitude ring, the ADI, and the 3D status markers. Status glyphs are 12px stroked SVG: a filled circle for ok, a filled triangle for caution, a hollow X for warning, and a dash for unknown.

## Components

### Joint dial (signature)
An EICAS round engine dial with a 210° sweep, spanning 20–90 °C.
- **Arcs:** green from the start to the caution limit (55 °C), 3 px at 55% opacity. Amber band from caution to warning (70 °C), 5 px at 75% opacity. A grey `border` arc above the warning limit, crossed by a 3 px red radial **redline** at the warning limit. Tick marks every 10 °C from 30 to 80, in `border-strong`.
- **Needle:** temperature needle in the status colour (2.5 px when nominal, 3.5 px otherwise, rounded caps), with a `surface-3` hub. An inner torque arc fills in `text-secondary` as a proportion of 20 Nm.
- **Readout box:** a mono temperature in a `surface-inset` box with a 2px radius. Caution gives amber text and an amber border. Warning gives a red fill with danger-ink text. Invalid shows amber `--`.
- **Caption:** a title-style segment name (HIP, THIGH, CALF). The dial diameter is 9.4u on the booth screen and 72px on a phone.

### Master annunciators
Two buttons, MASTER WARNING and MASTER CAUTION. When off they are a dark well with tertiary text. A lit CAUTION is solid amber with bg-base ink. A lit WARNING is solid red with danger-ink text and flashes at 1 Hz in two steps (inverting to well and red text). Annunciators latch while any unacknowledged finding of that severity exists. In staff mode, pressing one acknowledges it. They never light while telemetry is stale.

### Crew-alerting stack
An ordered list of messages on surface-2. Each message has a severity tag, the cited metric in mono, and the time on the right, then the agent's sentence below at headline size. The severity colours the border and the sentence: a WARNING has a red border and warning-text sentence, a CAUTION has an amber-mixed border and amber sentence, and an ADVISORY has an accent-outlined tag and a primary-text sentence. While telemetry is stale, an amber notice line ("Telemetry is stale…") sits above the list. When there are no findings, the stack says so plainly.

### Freshness lamp
A mono label in a well. **LIVE 0.9 s** shows a filled green circle. **STALE 45 s** (or **NO DATA**) shows a filled amber triangle and an amber border. Telemetry is stale after 15 s. An amber outlined **SYNTHETIC DATA** tag sits inside the lamp whenever the source is synthetic.

### Synoptic page keys
Chakra keys with a key-cap bevel on surface-2. The selected key is filled with the accent and set in accent-ink. Hover (staff mode, enabled keys only) raises the border to border-strong and the text to primary. In booth mode a 2px accent bar grows down the right edge of the key column over 12 s to show the auto-cycle.

### Readout cell
A well holding a title above a mono value. Caution turns the value amber and warning turns it red. A value that is missing renders `--` and hides its unit.

### Trend tape
A 300×60 strip chart plotted in a well. It has three `border-subtle` gridlines, dashed amber or red limit lines, and the trace drawn as a 1.5px `text-primary` line. The header shows a title and the last value in mono.

### Runtime-budget strip
Eighteen segments for 0–90 minutes. Lit segments are green at 85%, and all lit segments turn amber when less than 20% of the budget remains. A mono scale sits below. The strip is pinned under the crew-alerting stack next to the posture word.

### 3D Go2 and attitude ring
A Go2 built from MuJoCo Menagerie meshes, faced screen-left, with a gentle ±0.3 rad camera sway in booth mode. Joint housings lerp toward amber (by 0.55) or red (by 0.75) as their joint's status changes. Billboard markers appear at caution (scale 1.5) and warning (scale 2.2, with a slight pulse). Behind the dog, a thin `border` ring carries a fixed bank scale in `border-strong` (ticks every 10° to ±30°). An accent pointer and the horizon line rotate with roll and move with pitch. When telemetry is invalid they turn amber and dashed.

### Ask overwatch (staff only)
A title label, a surface-2 input with a 4px radius, and a tertiary note. The input is currently disabled at 70% opacity.

### Motion
Motion is instrument-like and nothing has an entrance animation. Needles, the torque arc, the attitude ring and the ADI ease with `cubic-bezier(0.16, 1, 0.3, 1)` over 400–600 ms (the ADI uses 500 ms). The WARNING annunciator flashes. The page-cycle bar runs linearly over 12 s. With `prefers-reduced-motion`, every CSS transition and animation drops to 0 ms, and the 3D gait, camera sway and marker pulse stop.

## Do's and Don'ts

### Do:
- **Do** take every accent from `var(--accent)`, `--accent-press` and `--accent-ink`, and add any new cloud only as a new entry in `THEMES` in `src/lib/theme.ts`.
- **Do** replace any stale or missing value with amber `--` (the EICAS invalid-data convention), and turn graphic instruments amber and dashed (`ATT FAIL`, a dashed horizon).
- **Do** pair every status colour with a shape or a label: lamp glyphs, status-list glyphs, severity words, annunciator words.
- **Do** put text on an amber fill in `bg-base` (#0B0E12) and text on a red fill in `danger-ink` (#1A0505).
- **Do** size new cockpit elements in `--u` multiples so they scale with the booth screen.
- **Do** set every changing number in JetBrains Mono with `tabular-nums`.
- **Do** label synthetic data on screen, using the amber SYNTHETIC DATA tag.

### Don't:
- **Don't** use a glow, gradient, blur or glass, or any outer drop shadow. Depth is borders plus the 1px top bevel.
- **Don't** use the cloud accent for a status, or a status colour for selection or branding.
- **Don't** use a radius above 6px on any structural surface.
- **Don't** add entrance animations, count-ups or bouncy easing to telemetry.
- **Don't** set sentences in Chakra Petch, or numbers in Plex.
- **Don't** hard-code a cloud name or a cloud hex in component code or copy.
