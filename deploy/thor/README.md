# Watch Dog on the Jetson AGX Thor

Watch Dog runs as a container on the Thor next to Elastic-Vision. It uses
Elastic-Vision's vLLM server (Cosmos Reason 2 8B) for scene narration.

## Everyday use

```bash
ssh thor 'demo-mode status'     # what's running, is Cosmos serving
ssh thor 'demo-mode watchdog'   # Watch Dog up, Elastic-Vision app stack down
ssh thor 'demo-mode elastic'    # the reverse
```

Dashboard: `https://<thor-ip>:8443` (HTTPS only; see Operator sign-in).

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
signed-in operator. Open endpoints: `/login`, `/logout`, `/healthz` (returns
only "ok") and static assets. Sign in once per browser; the session lasts
30 days. Sign out is in Settings.

```bash
ssh -t thor 'docker exec -it watchdog python3 auth.py set-password'   # change it
ssh thor 'docker exec watchdog python3 auth.py status'
```

- **HTTPS only, with a padlock.** The Thor and the AGX use certificates
  issued by a private "NTT DATA Watch Dog Demo CA". The CA key lives only on
  Raleigh's Mac in `~/.watchdog-ca/` and never goes in git. The CA carries
  critical name constraints: private IP ranges, `localhost`, `nvidia-thor`,
  `watchdog-agx`, and subdomains of those names. OpenSSL rejects certificates
  it signs for public names or IPs (tested: `www.google.com` and `8.8.8.8` both
  fail verification). **This is defence in depth, not a guarantee.** Browsers
  and the macOS keychain are not obliged to enforce constraints on a root you
  trust manually. Treat `ca.key` as a real secret: mode 0600 protects it from
  other users, not from a compromised account. Trust the CA once on each demo
  laptop and both dashboards load with a normal padlock:

  ```bash
  security add-trusted-cert -r trustRoot -k ~/Library/Keychains/login.keychain-db ~/.watchdog-ca/ca.pem
  ```

  Lifetimes and upkeep:
  - Device certificates expire about **2028-12-12** (820 days). The CA expires
    2031-09-22. Re-issue a device certificate before it expires, or when its
    IP changes: sign a new one with the CA, copy it to `/state/tls/` (Thor)
    or `tls/` (AGX), and restart the dashboard.
  - If the CA key is ever exposed, remove the trust on every laptop with
    `security delete-certificate -c "NTT DATA Watch Dog Demo CA"
    ~/Library/Keychains/login.keychain-db`, then create a new CA and re-issue
    both device certificates.
  - If no certificate is present, the Thor container falls back to a
    self-signed one, which browsers warn about.
- **Password change revokes sessions.** Every session is bound to a credential
  generation that rotates with the password, so an old session is refused on
  its next request, including one that was in flight during the change.
- **CSRF:** requests that change state must come from this exact
  scheme://host:port.
- **Throttling:** 5 failures per address and 30 overall per minute, counted
  before each password check, so parallel guesses can't slip past. While
  the overall limit is tripped, a legitimate operator also has to wait up
  to a minute. This state is in memory, so it resets when the container
  restarts. Clients behind one NAT share the per-address limit.
- **Loopback:** trusted on the AGX, for its on-box auto-arm supervisor.
  Disabled in the Thor container (`WATCHDOG_TRUST_LOOPBACK=0`).
- With no password set, the dashboard stays locked. The hash, signing key
  and generation live in `/state/auth.json` (mode 0600), never in git.
- `demo-mode` treats only the docker CLI's exact missing-container reply
  (`no such object: NAME`, docker 25–29 wording) as "absent". Any other
  docker error stops the switch.

## Remaining hardening (not done)

The container runs as root with the checkout mounted read-write, because the
app writes detection logs, UI state and the CLIP cache inside it. The next step
is a non-root user plus a read-only code mount with separate data directories.
Cosmos's vLLM server has no authentication of its own. It is reachable only on
Elastic-Vision's internal Docker network (no published port).
