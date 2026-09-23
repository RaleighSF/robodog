# Watch Dog on the Jetson AGX Thor

Watch Dog runs as a container on the Thor next to Elastic-Vision. It uses
Elastic-Vision's vLLM server (Cosmos Reason 2 8B) for scene narration.

## Everyday use

```bash
ssh thor 'demo-mode status'     # what's running, is Cosmos serving
ssh thor 'demo-mode watchdog'   # Watch Dog up, Elastic-Vision app stack down
ssh thor 'demo-mode elastic'    # the reverse
```

Dashboard: `http://<thor-ip>:8000`.

The two modes are exclusive because vLLM holds 80% of the Thor's memory.
Elastic-Vision's app, discovery, Elasticsearch and MinIO services only fit
alongside Watch Dog one at a time. vLLM stays up in both modes.

A user crontab entry runs `demo-mode apply` at boot. It waits for Docker,
starts vLLM before Watch Dog (vLLM must claim its memory first), waits until
the Cosmos model is actually serving, then restores the last mode. It retries
3 times.

## Deploying code changes

The app code is bind-mounted from `~/watch_dog`, so most changes need only:

```bash
# from the Mac, in the repo
rsync -a --files-from=<(git ls-files) . thor:watch_dog/ && rsync -a .git thor:watch_dog/
ssh thor 'cd ~/watch_dog/deploy/thor && docker compose restart'
```

Rebuild (`docker compose build`) only when `Dockerfile` or
`requirements-thor.txt` change. Every version is pinned to what was validated.

## Configuration

- `config.yaml` (repo) is the base.
- `deploy/thor/config.thor.yaml` is the Thor overlay: Cosmos backend, 8 s
  narrator interval, and `device_type: nvidia_agx_thor` for the NVIDIA badge.
- Dashboard edits are saved to the `watchdog-state` volume
  (`/state/config.yaml`). Overlay values are never baked into that file.

## Known gotchas

- The base vLLM image ships cuDNN 9.17.1 while its torch expects 9.18, so
  every convolution fails. The Dockerfile installs cuDNN 9.18.1 and puts it
  first on the library path.
- The GPU idles at 315 MHz and ramps to 1575 MHz under sustained load.
  Short benchmarks look slow; steady-state YOLO11m runs at ~110 FPS.
- Running `docker compose up -d` for Elastic-Vision by hand while in Watch Dog
  mode restarts its whole stack and breaks the memory budget. Switch with
  `demo-mode` instead.

## Operator sign-in

Every page, video stream and API call (robot control included) needs a
signed-in operator. Sign in once per browser; the session lasts 30 days.
Sign out is in Settings.

```bash
ssh -t thor 'docker exec -it watchdog python3 auth.py set-password'   # change it
ssh thor 'docker exec watchdog python3 auth.py status'
```

The password hash and session key are stored in `/state/auth.json` (the
`watchdog-state` volume, mode 0600), never in git. Changing the password signs
out every browser immediately. With no password set, the dashboard stays locked.

## Remaining hardening (not done)

The container runs as root with the checkout mounted read-write, because the
app writes detection logs, UI state and the CLIP cache inside it. The next step
is a non-root user plus a read-only code mount with separate data directories.
The dashboard is plain HTTP, so keep it on the demo network (Cradlepoint).
