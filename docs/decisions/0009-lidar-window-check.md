# 0009 Head lidar sensor-window check on the robot link
Date: 2026-10-30 · Status: Accepted

## Context
In the field, a smudged L1 lidar dome made the dog refuse to walk forward or back
while it could still turn. The lidar's own health stayed green (error 0, 15.4 Hz),
but it returned a ring of points close to the body on every side. Obstacle
avoidance treated that ring as walls. Cleaning the dome fixed it. Nothing in the
telemetry showed this.

## Decision
`go2_service` (Orin) runs a read-only `SensorWindow` monitor in its own DDS context
and thread, separate from the deadman's executor. It reads `/utlidar/cloud_base`,
`/utlidar/lidar_state` and `/multiplestate`.
- **Measurement:** while standing, it counts returns 0.30–0.60 m from the body and
  6–35 cm above the floor (floor = -body_height) in six 45° sectors across the
  front 270°. The L1 barely sees behind.
- **Rule:** if 5 or more sectors each have at least 20 returns/s for at least
  10 s, `window = obstructed`.
- **Calibration:** with a clean dome, 2 sectors were occupied (front, 140–240/s;
  sides 0–20/s). The dirty halo filled both sides at about 180–260/s.
- **Outputs:** `/vitals.lidar` → ADX columns `LidarWindow`, `LidarRingSectors`,
  `LidarHz`, `LidarErrorState`, `ObstacleAvoidance`.
- **Overwatch findings (medium):** "window dirty or boxed in", and "lidar
  degraded" (error > 0 or < 10 Hz).

## Consequences
- The rule was tuned on one clean capture and one dirty observation. A narrow
  aisle (walls within 0.6 m on both sides plus something ahead) can also trip it.
  The message says so, and avoidance would block walking there too.
- A failure in the monitor only blanks `lidar`. It never touches the command path.

## AWS parity
Nothing cloud-specific: the edge sends the same `lidar` block. Athena views add the
same five columns, and `Overwatch_Findings` adds the same two rules.
