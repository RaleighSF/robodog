#!/bin/bash
# Runs ON THE ORIN, from the private staging dir, invoked by build.sh.
# stdin: the sudo password (one line). Env: RDIR = this staging dir.
set -e
read -r pw
trap 'rm -rf "$RDIR"' EXIT
exec 9>/tmp/watchdog-go2-deploy.lock
flock -n 9 || { echo "another Watch Dog deploy is running on this Orin - try again after it finishes" >&2; exit 1; }
# Under the lock: sweep staging left by interrupted deploys (never our own).
find "$HOME" -maxdepth 1 -name "watchdog-go2.*" -type d ! -path "$RDIR" -exec rm -rf {} + 2>/dev/null || true
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
PREV="$(docker inspect -f '{{.Image}}' watchdog-go2 2>/dev/null || docker image inspect -f '{{.Id}}' watchdog-go2:latest 2>/dev/null || true)"
[ -n "$PREV" ] && docker tag "$PREV" watchdog-go2:previous
cp /etc/systemd/system/go2_service.service "$RDIR/prev.service" 2>/dev/null || true

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
