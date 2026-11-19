# 0006 Schema 1.1: full robot superset
Date: 2026-10-28 · Status: Accepted

## Context
The user wants every value the dog publishes captured, and the interesting ones plotted.

## Decision
- **Orin `/vitals`** (public read) exposes everything the Go2 publishes over DDS:
  - 12 joints (q, dq, ddq, tau_est, temperature, lost);
  - sport state (mode, gait, error, body height, position, velocity, yaw rate, obstacle
    ranges, foot data);
  - IMU;
  - BMS (soc, cycle, cell voltages, NTCs);
  - pack voltage and current;
  - board temperatures.
- **Thor** emits a `vitals` event every 5 s with that snapshot plus edge health.
- **Heartbeats** gain `posture`, `body_height` and `motor_temp_max`.
- The joint decoder (`motor_states`) lives in the shared go2dds library (additive), pinned
  in `deploy/orin/GO2DDS_REV`.

## Consequences
About 2.6 KB per vitals event, roughly 45 MB a day at 5 s. The joint order (FR, FL, RR,
RL; hip, thigh, calf) is the Unitree convention, to be confirmed on hardware.

## AWS parity
None needed beyond the sink: the schema is cloud-neutral by construction.
