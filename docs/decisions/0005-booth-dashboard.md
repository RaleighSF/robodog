# 0005 Booth dashboard: Next.js + TypeScript, EICAS direction, themeable per cloud
Date: 2026-10-30 · Status: Accepted

## Context
A large unattended booth screen, readable at about 3 m, plus a staff view. It must not
look like predictable AI-generated dashboards. See
`cloud/booth-dashboard/PRODUCT.md`.

## Decision
- **Stack:** Next.js + TypeScript (user's choice).
- **Visual world (pinned by the user):** Azimuth's industrial chassis
  (`~/Development/azimuth/DESIGN.md`) with an Azure-blue accent. There are no glows or
  gradients; colour carries status only.
- **Direction:** EICAS glass cockpit, chosen 2026-10-30 (impeccable seed d1423222, the
  assigned roll):
  - the 3D Go2 sits in an attitude-horizon ring;
  - 12 joint dials are grouped by leg;
  - agent findings form the crew-alerting stack;
  - all other vitals are on synoptic pages (POWER, GAIT, ATTITUDE, VISION, EDGE, LINK)
    that auto-cycle on the booth screen;
  - stale data uses the cockpit invalid-data convention.
- **3D:** three.js with the MuJoCo Menagerie Unitree Go2 meshes (BSD-3-Clause; the
  notice ships with the app).
- **Brand marks:** NTT DATA; Azure (plain text until the artwork is approved); Powered by
  NVIDIA; the Unitree Go2 name.

## Consequences
The cloud is a build-time theme plus an API base URL. Joint-to-leg mapping must be
confirmed on hardware before live posing.

## AWS parity
The same app is built with `THEME=aws` (AWS orange accent; brand marks swapped) and the
AWS query API URL. It is hosted on AWS Amplify Hosting or S3 + CloudFront.
