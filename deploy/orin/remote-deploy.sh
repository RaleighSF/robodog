#!/bin/bash
# Runs ON THE ORIN, from the private staging dir, invoked by build.sh.
# stdin: the sudo password (one line). Env: RDIR = this staging dir.
set -e
read -r pw
trap 'rm -rf "$RDIR"' EXIT
exec 9>/tmp/watchdog-go2-deploy.lock
flock -n 9 || { echo "another Watch Dog deploy is running on this Orin - try again after it finishes" >&2; exit 1; }
# Under the lock: sweep staging left by interrupted deploys - never our own,
# and only dirs untouched for an hour (a deploy still uploading is minutes old).
find "$HOME" -maxdepth 1 -name "watchdog-go2.*" -type d ! -path "$RDIR" -mmin +60 -exec rm -rf {} + 2>/dev/null || true
cd "$RDIR"
ID="$(docker build -q .)"
[ -n "$ID" ] || { echo "build produced no image" >&2; exit 1; }
echo "built $ID"
if ! printf "%s\n" "$pw" | sudo -S -p "" systemd-run --quiet --wait --pipe --collect \
      -p EnvironmentFile=/etc/go2_service.env \
      /usr/bin/docker run --rm -e GO2_AES_KEY -e GO2_SERVICE_TOKEN \
        -e GO2_TLS_CERT=/tls/cert.pem -e GO2_TLS_KEY=/tls/key.pem \
        -v /etc/watchdog-go2/tls:/tls:ro "$ID" --preflight; then
  echo "preflight failed - running service left untouched (see deploy/orin/README.md)" >&2; exit 1
fi

# Rollback point: the image the RUNNING container uses (falling back to the
# :latest tag if the service is down) and the installed unit file.
# Fail closed: an upgrade proceeds only with BOTH captured. A first install
# (no unit and no image yet) is the only case allowed without a rollback point.
set +e
UNIT=/etc/systemd/system/go2_service.service
# Tri-state lookups: prints the value (found), returns 3 for a CONFIRMED
# "No such ..." from the daemon, and aborts on any other error (daemon down,
# permissions) - an unknown state is never mistaken for absence.
lookup() {   # $1 = inspect subcommand args...
  local out rc
  out="$("$@" 2>&1)"; rc=$?
  if [ $rc -eq 0 ]; then printf '%s' "$out"; return 0; fi
  if grep -qi "no such" <<<"$out"; then return 3; fi
  echo "docker lookup failed ($*): $out - aborting (state unknown)" >&2; exit 1
}
# ($(...) runs lookup in a subshell, so its abort arrives here as rc 1.)
PREV="$(lookup docker container inspect -f '{{.Image}}' watchdog-go2)"; rc=$?
[ $rc -eq 0 ] || [ $rc -eq 3 ] || exit 1
if [ $rc -eq 3 ]; then
  PREV="$(lookup docker image inspect -f '{{.Id}}' watchdog-go2:latest)"; rc=$?
  [ $rc -eq 0 ] || [ $rc -eq 3 ] || exit 1
  [ $rc -eq 3 ] && PREV=""
fi
# Unit presence checked with privileges; only a confirmed "absent" counts.
printf "%s\n" "$pw" | sudo -S -p "" test -e "$UNIT"; urc=$?
case $urc in 0) UNIT_PRESENT=1 ;; 1) UNIT_PRESENT=0 ;; *) echo "cannot check $UNIT (rc $urc) - aborting" >&2; exit 1 ;; esac
if [ -z "$PREV" ] && [ "$UNIT_PRESENT" -eq 0 ]; then
  echo "first install (confirmed: no image, no unit) - no rollback point"
else
  [ -n "$PREV" ] || { echo "unit exists but no image found - refusing to upgrade without a rollback point" >&2; exit 1; }
  [ "$UNIT_PRESENT" -eq 1 ] || { echo "image exists but no unit - refusing to upgrade without a rollback point" >&2; exit 1; }
  docker tag "$PREV" watchdog-go2:previous || { echo "cannot tag rollback image - aborting" >&2; exit 1; }
  printf "%s\n" "$pw" | sudo -S -p "" cat "$UNIT" > "$RDIR/prev.service" && [ -s "$RDIR/prev.service" ] \
    || { echo "cannot back up $UNIT - refusing to upgrade without a rollback point" >&2; exit 1; }
  echo "rollback point: $PREV + saved unit"
fi
set -e

sudo_do() { printf "%s\n" "$pw" | sudo -S -p "" bash -c "$1"; }
install_and_restart() {   # $1 = unit file to install
  sudo_do "install -m 644 '$1' /etc/systemd/system/go2_service.service && systemctl daemon-reload && systemctl restart go2_service"
}
healthy() {
  # Verified like a client would: demo CA (staged beside the build), the
  # certificate's 127.0.0.1 SAN, a live DDS link AND video, within 90 s.
  local end=$((SECONDS + 90)) st
  while [ "$SECONDS" -lt "$end" ]; do
    st="$(curl -sf -m2 --cacert "$RDIR/ca.pem" https://127.0.0.1:5001/status 2>/dev/null || true)"
    if grep -q '"connected":true' <<<"$st" && grep -q '"has_video":true' <<<"$st"; then return 0; fi
    sleep 2
  done
  return 1
}
rollback() {
  echo "deploy failed: $1 - rolling back" >&2
  if [ -n "$PREV" ] && [ -f "$RDIR/prev.service" ]; then
    docker tag "$PREV" watchdog-go2:latest && install_and_restart "$RDIR/prev.service" && healthy \
      && echo "rolled back to $PREV with the previous unit (healthy)" >&2 \
      || echo "rolled back to $PREV - STILL NOT HEALTHY, check the robot" >&2
  else
    echo "no previous image/unit to roll back to" >&2
  fi
  exit 1
}
set +e    # every failure from here on goes through rollback()
docker tag "$ID" watchdog-go2:latest || rollback "tagging the new image"
install_and_restart "$RDIR/go2_service.service" || rollback "installing/restarting the unit"
healthy || rollback "new service not healthy (link + video) within 90 s"
echo "new service healthy ($ID)"
