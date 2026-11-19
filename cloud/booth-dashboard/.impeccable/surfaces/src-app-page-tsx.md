---
version: 1
slug: "src-app-page-tsx"
primary_target: "src/app/page.tsx"
related_targets: []
---

Scope: the booth dashboard's single route (`src/app/page.tsx`). Mode: Operate (glance at 3 m, plus staff at arm's length).
Audience: Ignite booth passers-by (seconds) and NTT DATA demo staff (who drive pages and ask the agent questions).
Job: show that a real Go2's full vitals are watched live from Azure, and that an agent overwatch reasons over them, read-only.

## Direction contract
THESIS: The dog is flown, not charted. It refuses the category default (KPI tiles over time-series cards). The screen is an EICAS glass cockpit: engine-style joint dials, a crew-alerting stack spoken by the agent, and synoptic pages for every other system.
OWN-WORLD: Azimuth chassis: near-black cool-blue panels lifted by 1px borders and one inset top bevel, with no glow, gradient or glass. Status colours have fixed meanings: green nominal, amber caution, red warning, grey unknown. Azure blue is the only accent: advisories, selection, focus. Chakra Petch (uppercase) for panel titles, IBM Plex Sans for UI text, JetBrains Mono tabular figures for every number. EICAS invalid data replaces a stale value with amber dashes. Dials use the cockpit convention: a green arc, an amber band and a red line.
STORY: A visitor sees a real robot's body mirrored live, every joint reading like an engine. The agent's crew-alerting messages explain what it notices, such as "RL calf 61 °C — sit the dog to cool", and those messages are what make them stop. Staff page through POWER, GAIT, ATTITUDE, VISION, EDGE and LINK to go deeper.
FIRST VIEWPORT: 16:9. A top strip, about 6% of the height, holds the NTT DATA mark, the robot ID, master WARNING and CAUTION annunciators, the freshness lamp ("LIVE 1.2 s" or "STALE 45 s"), "Built on Microsoft Azure" and "Powered by NVIDIA". The left 62%: the 3D Go2 large on a dark field inside a thin attitude-horizon ring whose bank and pitch follow the IMU. Its four leg quadrants (FL, FR at the front; RL, RR at the rear) each carry three joint dials (hip, thigh, calf: temperature arc plus a torque needle) placed near their leg. The right 38%: the crew-alerting stack, with the agent's messages ranked WARNING, CAUTION and ADVISORY, each with a time, a cited metric and the agent's sentence. Beneath it sit the posture state and the battery runtime-budget strip. The bottom strip holds the synoptic page keys; on the booth screen the current page auto-cycles in a lower band. The primary action for staff is the page keys plus an "Ask overwatch" field, which is staff-only and hidden in booth mode.
FORM: EICAS glass cockpit (my grounded list, candidate 4 of 7), seed d1423222. The signature interaction is the master-caution cycle: a new agent finding enters the stack, the matching annunciator latches, and the joint's marker grows on the 3D body until staff acknowledge it. The motion grammar is instrument-like: needles ease out, and there are no entrance animations.
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Constraints
Read-only; no robot commands. Synthetic data is labelled SYNTHETIC on screen. Joint mapping is unconfirmed until hardware validation. Thresholds are placeholders.
