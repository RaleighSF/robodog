# Learnings (Sept 2026: Thor migration, firmware 1.1.15, venue hardening)

These are hard-won and non-obvious. Read them before touching the robot link,
the Thor image, or gestures.

## Robot / Go2 firmware 1.1.15
- **Commands moved to DDS.** WebRTC commands stopped working. Copy Azimuth's
  transport (rclpy + CycloneDDS, ROS 2 Humble, `unitree_api`/`unitree_go`
  messages) rather than the Unitree Python SDK, which segfaulted on the Orin
  host.
- **Video still needs WebRTC**, with the per-device AES key.
  `unitree_webrtc_connect` 2.0.0 has no AES parameter; 2.2.0 (as in Azimuth's
  image) does.
- **A lying dog answers StopMove with -1.** Verify a stop by physical rest on
  fresh telemetry plus *any* reply. Never by reply code alone, and never by
  stillness alone: that would hide a dead command channel.
- **Speed floors are real.** Below 0.22 m/s forward the gait stalls after
  about 1.8 s while still acknowledging every Move. Below 0.45 rad/s it
  doesn't turn. Snap small commands up to the floors.
- **Posture from body height**: under 0.15 m is lying, under 0.27 m is low,
  otherwise standing. From low, send RiseSit (1010), not RecoveryStand.
- **Watch Dog and Azimuth never run together.** Systemd `Conflicts=` coordinates
  the processes on the Orin; it does not mediate the robot itself.

## Driving safety (from 9 rounds of Astra review)
- The old D-pad sent a stop before every press, and mouseup/blur sent stops
  constantly. That was the "D-pad doesn't work" bug. Fix: per-press sessions,
  and stop only when a press is actually active.
- "Stopped" must mean verified at rest, and each stop is confirmed only for
  its own number. An E-stop must stay latched until confirmed.
- A timed-out HTTP request isn't a cancelled one. `future.cancel()` can't
  recall a request that's already on the wire. Late delivery is handled on
  the *robot* side (retired sessions, seq, permits), not by the client
  timing out.
- requests' `(connect, read)` timeouts bound inactivity, not total time.
  Enforce a total deadline separately.
- Don't quote a stopping distance you haven't measured. Permits bound how
  *old* an admitted command can be, not braking.

## Deploying
- Pin everything: the base image by ID, go2dds by commit (`git archive`), and
  vLLM by digest.
- Run the preflight **inside the new image** with the unit's real environment
  (`systemd-run -p EnvironmentFile=`). Grepping the env file isn't validation.
- Never read "state unknown" as "absent". Use successful empty listings
  (`docker ps -a -q --filter`, `docker images -q`) and explicit sudo markers.
  Don't match error text.
- `exit` inside `$(...)` only leaves the subshell. Check the return code at
  the call site.
- Bash can't parse some heredocs inside `$(...)`, so put remote scripts in
  their own file.
- zsh doesn't word-split `$VAR`: use arrays for ssh options. rsync failed to
  the Thor more than once; scp of the changed files is reliable.
- A deploy with the dog switched off rolls back by design, because the health
  check needs the link and video.

## Thor (JetPack 7, CUDA 13.2)
- The NVIDIA vLLM 26.01 image's torch expects cuDNN 9.18 but ships 9.17.1, so
  every convolution fails ("unable to find an engine"). Install
  `nvidia-cudnn-cu13==9.18.1.3` first on `LD_LIBRARY_PATH`.
- Pin constraints with `pip list --format=freeze`. A regex over requirements
  misses `@ file://` installs, so torch silently wasn't pinned.
- The GPU idles at 315 MHz and ramps up under sustained load. Short benchmarks
  mislead: YOLO11m reaches about 110 FPS steady-state.
- vLLM holds about 80 % of the 122 GB, so Watch Dog fits only with
  Elastic-Vision's app stack down. Always switch with `demo-mode`.
- A config reload must rebuild into a private dict and swap it in. Otherwise
  the overlay (such as `device_type`) gets clobbered, which showed "Orin" on
  the Thor badge.

## Gestures
- YOLO-World hand detection is unreliable on Ultralytics 8.4. Confidence sat
  around 0.15; loosening thresholds caused a false-shake spree.
  **MediaPipe hand landmarker** is reliable: at least 2.5 % of the frame and a
  2-of-4 vote.
- Gate the decision on the *capture* time of the exact frame, and re-check
  arming after inference. Otherwise a shake can fire on an old picture or
  after the operator has left the Gesture tab.
- Arming is a lease renewed by the visible Gesture tab, never armed at boot.

## TLS / certificates
- A name-constrained demo CA gives a padlock on demo laptops. A certificate SAN
  outside the constraints (such as `DNS:watchdog-orin`) fails with "permitted
  subtree violation". Use IP SANs plus `localhost`.
- Pin the demo CA as the *only* trust anchor for the robot link. A system-store
  verify must fail (tested).
- Keep reads and control on separate HTTP sessions, so the control token never
  travels on public reads.

## Process
- "Check with Astra" means sending the review to Codex (`codex:codex-rescue`)
  and iterating until ACCEPT.
  - Ask it to separate BLOCKING findings from acceptable residuals, or the
    loop keeps widening.
  - Take genuinely structural fixes (robot permits) to the user as a decision.
