# Unitree Go2 health knowledge base (overwatch agent)

Scope: Go2 EDU-class, firmware 1.1.15, head L1 4D lidar, Jetson Orin dock. Researched 2026-10-30.
Rules for the agent: a tag of **[official]** means a Unitree document or the Unitree SDK. **[distributor]** means a reseller's document. **[community]** means a third-party repo, issue, or forum post, and is unverified. **[local]** means something observed on this robot, which no public document backs up. Do not state any number that is not in this file.

## 1. Joint motors (temperature, heat, comms)
- The Go2 has 12 joint motors, a joint heat-pipe cooler on every version, and a peak joint torque of about 45 N·m on PRO/X/EDU [1] [official].
- Telemetry: each `MotorState` carries `temperature` (int8, °C), `q`, `dq`, `tau_est`, and `lost` (uint32). `LowState` also carries `temperature_ntc1/ntc2`, `power_v`, `power_a`, and `fan_frequency[4]` [11][12] [official]. No public Unitree document says what `lost` means. A rising `lost` counter is most likely dropped motor frames, but treat that as an inference.
- Heat causes [official]: the manual says lower body height and more knee bend "place a greater burden on the motors", raising power draw and causing "motor heating". Long periods of attitude adjustment while standing, bent-leg standing, load carrying, fast walking and slopes all cut endurance [3].
- Standing still heats the rear hip motors. One integrator measured **76 °C on the rear hips against 33–42 °C on the other joints**, and recommends lying the dog down when idle [16] [community].
- **No official Go2 motor over-temperature threshold was found.** Do not quote 80 °C or 90 °C as Go2 limits. The app error table has entries for "Winding overheating" (300-10), "Driver overheating" (300-4) and "Overheating software protection" (600-4), so firmware does detect and act on overheating [13] [community, extracted from the Unitree app].
- Other app motor faults: Overcurrent (300-1), Overvoltage (300-2), Generatrix [bus] undervoltage (300-8), Encoder abnormal (300-20), Motor communication interruption (300-100), and Motor communication error (100-80) [13].
- Fans: the app reports "Rear left/Rear right/Front fan jammed" (200-1/200-2/200-4) [13]. The pre-use checklist asks staff to check that the heat-sink inlet and outlet are not blocked [3] [official].
- **Recommended cool-down:** there is no official procedure. Lying down or sitting removes the standing load described above [3][16], but that comes from inference plus a community report.

## 2. Battery / BMS
- The standard pack is BT2-05: 8000 mAh, 236.8 Wh, rated DC 29.6 V, charge limit DC 33.6 V, charging current 3.5–9 A [2] [official]. The robot runs on 28–33.6 V [1] [official].
- **EDU ships with the long-endurance 15000 mAh pack and a 33.6 V 9 A fast charger, rated "about 2–4 h"**. AIR/PRO/X get the 8000 mAh pack, rated about 1–2 h [1] [official]. The distributor lists the BT2-06 pack as 15000 mAh / 432 Wh / 28.8 V, with a 3–5 h runtime and about 1 h 15 min charging on the 9 A charger [4] [distributor]. That runtime is higher than Unitree's own 2–4 h figure.
- The 1–2 h figure assumes "no load static standing and upright walking alternately" [3] [official].
- BMS protections: balanced charge, overcharge, over-discharge, short circuit, charging temperature, charging current, storage self-discharge, and load detection [2] [official].
- Telemetry `BmsState`: `soc` (uint8 %), `current` (int32), `cycle` (uint16), `status`, `bq_ntc[2]`, `mcu_ntc[2]`, and `cell_vol[15]` (uint16) [11] [official]. The array has 15 slots, but that does not mean the pack has 15 cells. **Cell count is unverified.** 33.6 V / 4.2 V = 8 suggests an 8-series Li-ion pack (inference only). Any trailing `cell_vol` slots that read zero are probably unused, but that is not verified.
- **Low battery:** the head light flashes yellow slowly for "low battery warning, will automatically crouch down within 10 minutes" [3] [official]. The app also has a "Low battery software protection" fault (600-8) [13].
- Over-discharge protection cuts output at 24 V [5]. This comes from a ManualsLib copy of the battery manual, so verify it against the original.
- Charging: do not charge below 0 °C or above 50 °C [5]. Charge with the pack removed from the robot and use only the Unitree charger [5]. Never charge when it is too hot or too cold, never store above 40 °C, and do not overcharge [3] [official].
- Storage: if SOC is below 30%, charge to 70% before storing [3] [official]. For transport, discharge to about 65% [5].
- "Battery communication error" (100-10) is an app fault [13].
- **Cycle life: not published.** No official figure was found.

## 3. Sport-mode state / error codes
- `SportModeState.error_code` is a uint32 labelled only "Error code". **Unitree publishes no meaning for its values** [12] [official]. One integrator could find no enumeration in the SDK, and another reported that it goes from 1001 before StandUp to 1002 after StandUp and then stays at 1002 even while the robot ignores Move [15] [community].
- [local] On this robot we see: 100 while standing, 1001 while lying, 1002 during posture transitions, and 1013 / 2010 when obstacle avoidance blocks motion. None of these meanings is documented.
- The numbers match some API IDs, but the meaning may differ. Sport API IDs: Damp = 1001, BalanceStand = 1002, StopMove = 1003, StandUp = 1004, StandDown = 1005, RecoveryStand = 1006 [8] [official]. The legacy WebRTC command list puts BodyHeight at 1013 [13] [community]. **No source lists 100 or 2010.** In the MCF API space the 20xx IDs run 2041–2058 [8]. Treat any mapping from these codes to states as a hypothesis.
- Do not confuse these with SDK RPC return codes. In those, 0 = success, 1001 = "common error", 1002 = "bad cast" and 1012 = timeout [9]. Sport RPC errors: 4101 "point path error", 4201 "server overtime", 4205 "server function not init" [10]. Robot-state errors: 5201 "service switch error", 5202 "service is protected" [10]. **3203 = "API not implemented" on firmware 1.1.15** [19] [community].
- Community remedy: if the robot answers queries but ignores posture commands and reports `error_code: 1001`, the motion controller is stuck and needs reloading [16] [community].
- `mode` (uint8) does have published meanings: 0 idle/default stand, 1 balanceStand, 2 pose, 3 locomotion, 5 lieDown, 6 jointLock, 7 damping, 8 recoveryStand, 10 sit, 11 frontFlip, 12 frontJump, 13 frontPounce. `gait_type`: 0 idle, 1 trot, 2 run, 3 climb stair, 4 forwardDownStair, 9 adjust [12] [official]. Prefer `mode` over `error_code` when explaining posture.
- **App fault channel.** This channel is separate from `error_code`. It comes over WebRTC as `errors`, `add_error` and `rm_error` messages carrying `[timestamp, source, code]`, with the code read as hex [14] [community]. Sources: 100/200 communication firmware, 300 motor, 400 radar (lidar), 500 UWB, 600 motion control [13]. The handler looks up one hex code per entry, so a code with several bits set may not decode.

## 4. Obstacle avoidance and the L1 lidar
- Go2 avoidance uses the L1 data and **only avoids obstacles ahead** [3] [official]. Avoidance is on by default and the head light is solid green. Solid blue means avoidance is off [3]. Toggles: on the EDU remote, X turns avoidance on and holding Y for 3 s turns it off [4] [distributor]. On the companion remote, press L2 twice for on and once for off [3].
- Unitree's own tip: choose an open route "to minimise the triggering of the robot's own autonomous avoidance" [3] [official]. A cramped booth will set it off.
- L1 specs [6][7] [official]:
  - Field of view: 360° × 90° hemisphere. Point density is higher toward the centre of the FOV.
  - Near blind zone: 0.05 m, and data at that range is "for reference only".
  - Range: 30 m for RM / 20 m for PM at 90% reflectivity, and 15 m / 10 m at 10% reflectivity.
  - Scan rate: 11 Hz horizontal, 180 Hz vertical, 21,600 effective points/s.
  - Accuracy: ±2.0 cm.
  - Anti-strong-light: 100 klux.
  - Environment: −10 to 60 °C, IP54, 905 nm Class 1 laser, 12 V, about 6 W.
- Known degraders [6][7] [official]:
  - Haze and heavy rain shorten range.
  - Glass in front of the window affects performance.
  - Dust or dirt on the window degrades the data.
  - High temperature: once the housing reaches 60 °C the lidar raises an over-temperature warning, and in severe cases it stops.
- **Dirty dome:** the app has a radar fault "Abnormal dirt index" (400-10). Related faults: "PointCloud data abnormal" (400-2), "Serial port data abnormal" (400-4), and "Motor rotate speed abnormal" (400-1) [13].
- **Lidar stops spinning:** if an external force stops it, it should restart by itself once the force is released. If not, nudge it by hand, then reboot the Go2, then check the app [3][7] [official].
- **Cleaning [official]:** power off first. Wipe the window gently with a clean lens cloth. If stains remain, add a small amount of alcohol to the cloth [7]. Do not touch the optical window with bare hands [6]. Check for dust around the head lidar before each use [3].
- `SportModeState.range_obstacle[4]` exists [12]. One user found it read all zeros, and that the robot became hard to control when avoidance met an obstacle [17] [community]. Do not rely on `range_obstacle`.
- Glass, mirrors and other reflective surfaces: **no Go2-specific source was found** beyond the "glass in front of window" note. Sunlight: only the 100 klux spec is available.

## 5. Foot force sensors
- Foot-end force sensors are fitted **only on EDU** [1] [official]. `LowState` has `foot_force[4]` and `foot_force_est[4]` (int16), and `SportModeState` also has `foot_force[4]` [12] [official].
- **No units, typical values or failure modes are published.** Readings of zero on a non-EDU robot are expected, since the hardware is not there. Zero readings on an EDU are unexplained in public sources.
- The feet themselves are consumables. Replace a foot that shows obvious pad wear or damage, or that makes loud noise while walking [3] [official].

## 6. IMU, falls and tilt
- IMU data is in `SportModeState.imu_state` and `LowState.imu_state` [12]. The L1 also has its own 6-axis IMU (1 kHz sampling, 250 Hz output) [6].
- Recovery: `RecoveryStand` (API 1006, mode 8) is used after a fall [8][12]. Firmware has `SetAutoRecovery` / `GetAutoRecovery` (API 2054/2055) [8] [official]. **The default setting is undocumented.** On the companion remote, a long press of P for 1 s after a side roll makes the robot stand again [3]. On the EDU remote, L2 (long) + X stands it up after a fall [4] [distributor].
- Emergency stop: damping mode is L2 (long) + B on the EDU remote [4]. Only switch off while the robot is lying down, or it will drop heavily [3] [official].
- Slopes: rated for climbs of 40° or less (AIR 30°). At about 40° and above the body drifts sideways, and turning on a steep slope can destabilise it. Maximum step height is 16 cm [3] [official].
- The commanded posture envelope via `Euler` is roll/pitch ±0.75 rad and yaw ±0.6 rad. BodyHeight offset is −0.18 to 0.03 [22] [community]. **No official "abnormal roll/pitch" threshold exists.** As an inference, sustained roll or pitch beyond ±0.75 rad (about 43°) without a posture command suggests a fall.
- If the posture is abnormal or the dog falls easily after boot, restart. If that fails, consult Unitree before running joint/IMU recalibration, which is factory-set [3] [official]. A slow blue flash means calibration is in progress. A fast red flash means calibration failed. A slow red flash means a system or hardware fault [3].

## 7. Environment and booth safety [official unless noted]
- Ambient operating range: 5–35 °C, fair weather only [3].
- The robot is **neither waterproof nor dustproof**. Do not run it on wet floors or gravel, or in dust [3]. No IP rating is published for the whole robot. The L1 itself is IP54 [6].
- Floors:
  - No ice-like low-friction floors and no thick spongy floors.
  - On glass or ceramic tile, move gently and slowly to avoid foot slip [3].
  - Do not make strenuous posture changes on low-friction ground [3].
  - Forbidden: wet ground, debris on the floor ("sundries"), steps over 16 cm, slopes over 40°, sharp objects [3].
  - **Cables and carpet are not addressed in any source.**
- Payload: EDU about 8 kg, maximum about 12 kg [1].
- People: keep at least 2 m from crowds, obstacles and water, within line of sight [3]. Not for users under 14 [3]. Do not lift the robot while it is powered [3]. Kicks and hard pushes are not covered by warranty [3]. Knee joints can pinch hands [3].
- RF: avoid Wi-Fi co-channel interference and EMI sources. The manual suggests turning off other Wi-Fi sources if control is affected [3]. This matters on a trade-show floor.

## 8. Firmware 1.1.x notes [community unless noted]
- Firmware 1.1.15 wraps the WebRTC LAN handshake in a per-device AES-128 key (`data2 == 3`). Older clients fail with "RSA key format is not supported" [18][20].
- Since 1.1.7, an MCF sport API space is in use, with different IDs (for example BackFlip 2043 instead of 1044) [13]. On 1.1.15 several legacy commands return 3203 [19]. On one robot the only motion controller was `mcf`, and `BalanceStand` was accepted but did nothing [16].
- Over WebRTC, `rt/lf/lowstate` runs at about 1 Hz and `rt/lf/sportmodestate` at about 20 Hz on 1.1.15 [20]. Treat low-state values, including temperatures and BMS, as coarse 1 s samples.
- "Sports mode has been merged into A.I mode" in recent firmware, according to one forum reply [21].
- `range_obstacle` reads zero [17]. `error_code` stays at 1002 while Move is silently ignored for 4–10 s or more after StandUp [15].
- The manual's pre-use step is: make sure the firmware is the latest version [3] [official].

## 9. Pre-demo-day operator checks
Sourced from the official checklist [3] unless noted.
- Appearance: the body is clean and undamaged, the camera lens is clear, and **there is no dust on the head lidar**. Clean the window per [7].
- Structure: joints, links and feet are intact. Screws are tight, especially at the joint connectors and the battery locking knob. **Heat-sink inlets and outlets are clear.**
- Feet: no obvious pad wear. Swap in the spare if needed.
- Battery: the interface is clean and undeformed, and the pack is seated with a click. Never use a damaged pack. The charge is sufficient. Charge at 0–50 °C [5].
- Remote: keys are not sticky, the sticks work, and the remote is charged. The emergency damping combo is known (L2 + B) [4].
- On boot: the light flashes green, then goes solid green (avoidance on). A red light means stop and investigate [3].
- Booth plan: lie the dog down between demos to cut hip heat [16] [community]. Keep a 2 m buffer from the crowd. Keep the floor dry and free of debris. Avoid reflective glass in the forward path (inference).

## Sources
1. https://www.unitree.com/go2 — Unitree Go2 product page and spec table (the current page shows the L2 lidar; earlier units such as ours have the L1)
2. https://www.unitree.com/go2/battery — Unitree "Go2 Battery"
3. https://static1.squarespace.com/static/5e76e0c52a318c0c1a850442/t/6670b3b47b72423f1b3b0e5b/1718662095370/GO2+User+Manual.pdf — Unitree Go2 AIR/PRO User Manual (© 2023 Unitree, copy hosted by a dealer)
4. https://www.docs.mybotshop.de/downloads/GO2_User_Manual.pdf — MYBOTSHOP / QUADRUPED Robotics "Unitree Go2: User Manual" (distributor)
5. https://www.manualslib.com/manual/3377276/Unitree-Go2.html — Unitree Go2 battery & charger manual (ManualsLib copy)
6. https://oss-global-cdn.unitree.com/Lidar/L1%20Quike%20Start%20Guide_v1.0.pdf — Unitree 4D LiDAR-L1 Quick Start Guide v1.0
7. https://oss-global-cdn.unitree.com/static/52b72f707b304d229d4321eea223738f.pdf — Unitree 4D LiDAR-L1 User Manual v1.1 (2024.06)
8. https://github.com/unitreerobotics/unitree_sdk2/blob/main/include/unitree/robot/go2/sport/sport_api.hpp — unitree_sdk2 Go2 sport API IDs
9. https://github.com/unitreerobotics/unitree_sdk2/blob/main/include/unitree/common/error.hpp — unitree_sdk2 common error codes
10. https://github.com/unitreerobotics/unitree_sdk2/tree/main/include/unitree/robot/go2 — unitree_sdk2 Go2 sport_error.hpp / robot_state_error.hpp
11. https://github.com/unitreerobotics/unitree_sdk2/tree/main/include/unitree/idl/go2 — unitree_sdk2 Go2 IDL (LowState_, MotorState_, BmsState_, SportModeState_)
12. https://github.com/unitreerobotics/unitree_ros2 — unitree_ros2 README (message definitions, mode/gait meanings)
13. https://github.com/legion1581/unitree_webrtc_connect/blob/master/unitree_webrtc_connect/constants.py — unitree_webrtc_connect constants (app error table, SPORT_CMD, MCF IDs)
14. https://github.com/legion1581/unitree_webrtc_connect/blob/master/unitree_webrtc_connect/msgs/error_handler.py — unitree_webrtc_connect error handler
15. https://github.com/unitreerobotics/unitree_sdk2_python/issues/175 — "Move() ignored ... after StandUp() with no readiness signal in SportModeState"
16. https://github.com/giangalv/ter_go2 — ter_go2 README (integrator notes)
17. https://github.com/abizovnuralem/go2_ros2_sdk/issues/234 — go2_ros2_sdk "Obstacle Avoidance Error"
18. https://github.com/abizovnuralem/go2_ros2_sdk/pull/240 — "Support per-device AES-128 key for WebRTC handshake (Go2 firmware >= 1.1.15)"
19. https://github.com/0gfoundation/zerobot/pull/51 — "Match the Go2 command list to firmware 1.1.7+"
20. https://github.com/0gfoundation/zerobot/pull/3 — "Connect to Go2 firmware 1.1.15 and fix handshake bugs found on hardware"
21. https://forum.mybotshop.de/t/unitree-go2-edu-sports-modes-keep-crashing/1480 — MYBOTSHOP forum "[Unitree Go2 Edu] Sports Modes keep crashing"
22. https://unitree-go2-robot.github.io/humble/api_interfaces/index.html — Intelligent Robotics Lab "API Interfaces" (community Go2 ROS 2 docs)
