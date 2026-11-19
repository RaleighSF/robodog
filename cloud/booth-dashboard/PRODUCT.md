# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Next.js + TypeScript (user's choice, 2026-10-28). Hosted on Azure Static Web Apps for
Microsoft Ignite; the same app redeploys to AWS for re:Invent with a configuration
switch, so the cloud is never hard-coded in the UI. Data comes only through the
provider-agnostic, read-only telemetry query API (`cloud/query_api`; operations
`vitals_latest`, `vitals_series`, `motors_latest`, `motors_series`, `posture_timeline`,
`detections_summary`, `alerts_recent`, `commands_recent`, `overwatch_findings`).
3D: three.js with the MuJoCo Menagerie Unitree Go2 meshes (BSD-3-Clause, Unitree
copyright; the notice ships with the app).

## Users

- **Booth passers-by at Microsoft Ignite.** They see the dashboard on a large booth display
  that runs unattended. They glance at it from about 3 m for a few seconds and decide
  whether to stop.
- **NTT DATA demo staff.** They run the same app on a laptop or tablet to drive the
  story. They point at vitals, ask the agent overwatch questions, and explain what the
  robot is doing.

## Product Purpose

The dashboard shows a live Unitree Go2 robot dog's health and situation from the cloud:
- the 12 joint motors (temperature, torque, angle);
- posture and tilt;
- battery and BMS;
- edge-compute health;
- detections and PPE alerts.

It also shows an AI **agent overwatch** that watches the same telemetry and narrates
trends, raises alerts and answers staff questions.

Success means a passer-by understands in seconds that a real robot's vitals are being
watched live from Azure, and staff can turn that into a credible conversation about
NTT DATA Physical AI ("AI that sees, reasons, acts").

## Positioning

The data is real and live from the physical robot on the booth floor, carried as the same
telemetry schema to whichever cloud runs the show. The agent is grounded only in that
telemetry, read through a fixed query API, and is read-only by design: it never commands
the robot.

## Operating Context

- **Booth network.** The dog (Orin), a Cradlepoint router and the Jetson AGX Thor edge
  computer run at the booth. The Thor streams telemetry to the cloud (Azure Event Hubs,
  then Azure Data Explorer), so live data needs booth internet. The local Watch Dog
  dashboard on the Thor remains the robot's control surface. This cloud dashboard is
  view-only.
- **Telemetry rhythm.** `vitals` events arrive about every 5 s and heartbeats every 30 s.
- **Robot behaviour.** The dog sits or lies between demos because idle standing overheats
  the motors. That is a real, demonstrable finding for the overwatch.

## Capabilities and Constraints

- **Read-only.** There are no robot commands anywhere in this product.
- **Stale telemetry and lost links must be unmistakable.** A frozen number that looks live
  is the worst failure. Show age and connection state explicitly.
- **Agent chat is staff-only.** The agent posts findings to a visible feed on its own.
  Only demo staff type questions; visitors do not type freely at a public booth.
- **Must re-skin to AWS for re:Invent.** Brand and accent are themeable tokens, not
  hard-coded.
- **Joint mapping is unconfirmed.** Joint order on the real dog is FR, FL, RR, RL legs,
  each hip, thigh and calf, per Unitree convention. It must be confirmed on hardware
  before the 3D legs are driven by live angles.
- **No paid image or 3D generation.**
- **Alert thresholds are placeholders.** Joint above 70 °C, battery below 20%, tilt above
  about 35°. Do not present them as Unitree specifications.

## Brand Commitments

- **NTT DATA** mark (company; "AI that sees, reasons, acts").
- **Microsoft Azure.** Use only approved artwork. Until approved, show a plain-text "Built
  on Microsoft Azure", per the Watch Dog demo-profile logo rules.
- **"Powered by NVIDIA"** badge, for the Jetson AGX Thor.
- **Unitree Go2** may be named on screen (user-approved 2026-10-28). Marketing should
  confirm trademark use. The model license does not cover the name.

## Evidence on Hand

- Live telemetry schema 1.1: `TELEMETRY_SCHEMA.md`.
- Azure Data Explorer free cluster `kvc-n5g99ncbrcxpzed6md.southcentralus` with database
  `watchdog`. It currently holds only **synthetic sample data** (device `watchdog-sample`).
  Never present that data as the real robot's.
- MuJoCo Menagerie Go2 meshes (BSD-3-Clause).
- No customer logos, testimonials or benchmark claims exist. Do not fabricate them.

## Product Principles

1. **Live or clearly not.** Every value shows its freshness. Stale data is visibly
   stale, never silently frozen.
2. **The robot is the hero.** The physical dog, mirrored in 3D, anchors the screen. Every
   panel explains something about it.
3. **Grounded agent.** The overwatch speaks only from telemetry it queried, cites what it
   saw, and never acts on the robot.
4. **Glanceable at 3 m, deep at arm's length.** The booth view reads in seconds. The staff
   view rewards a closer look.
5. **Cloud-portable.** Nothing in the experience depends on which cloud hosts it.

## Accessibility & Inclusion

WCAG 2.2 AA contrast. Status is never conveyed by colour alone (a label or shape
accompanies it). Motion respects `prefers-reduced-motion`. Large-screen legibility at
about 3 m.
