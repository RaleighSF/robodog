#!/usr/bin/env bash
# Build and install the Watch Dog robot link on the dog's Orin, from the Mac.
#   deploy/orin/build.sh [unitree@<orin-ip>]
# Stages go2_service.py, this folder and the shared go2dds package at the
# revision pinned in GO2DDS_REV (exported with `git archive` from the sibling
# checkout GO2DDS_DIR, default ../go2dds - uncommitted edits there are never
# shipped), builds the image on the Orin, runs its --preflight against the
# unit's real environment, then installs the unit and restarts the service.
set -euo pipefail
HOST="${1:-unitree@10.0.0.57}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
GO2DDS_DIR="${GO2DDS_DIR:-$(cd "$REPO/.." && pwd)/go2dds}"
REV="$(tr -d '[:space:]' < "$HERE/GO2DDS_REV")"
git -C "$GO2DDS_DIR" cat-file -e "$REV^{commit}" 2>/dev/null \
  || { echo "go2dds revision $REV not found in $GO2DDS_DIR (fetch it first)" >&2; exit 1; }
: "${SSHPASS:?export SSHPASS (the Orin password) first}"
SSH_OPTS=(-o StrictHostKeyChecking=no -o IdentitiesOnly=yes -o PubkeyAuthentication=no -o LogLevel=ERROR)
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
cp "$HERE/Dockerfile" "$HERE/entrypoint.sh" "$HERE/go2_service.service" "$REPO/go2_service.py" "$STAGE/"
git -C "$GO2DDS_DIR" archive "$REV" go2dds | tar -x -C "$STAGE"
echo "$REV" > "$STAGE/go2dds/REVISION"
# Private staging dir per deploy on the Orin (no shared mutable paths).
# Stale dirs from interrupted deploys (connection lost before any cleanup ran)
# are swept here, before allocating a new one.
RDIR="$(sshpass -e ssh "${SSH_OPTS[@]}" "$HOST" 'find "$HOME" -maxdepth 1 -name "watchdog-go2.*" -type d -mmin +60 -exec rm -rf {} + 2>/dev/null; mktemp -d "$HOME/watchdog-go2.XXXXXX"')"
# From allocation on, this side removes it too (covers scp/ssh/password failures).
trap 'rm -rf "$STAGE"; sshpass -e ssh "${SSH_OPTS[@]}" "$HOST" "rm -rf $(printf %q "$RDIR")" 2>/dev/null || true' EXIT
sshpass -e scp -r "${SSH_OPTS[@]}" "$STAGE"/* "$HOST":"$RDIR"/
# Build, then run THAT image's --preflight (by image ID, never a shared tag)
# with exactly the environment the unit will get (systemd-run applies
# EnvironmentFile= with systemd's own parsing) and the same TLS mount; promote
# the same ID only if it passes. The whole step is serialized by a lock, so a
# concurrent deploy fails fast instead of interleaving.
# The script travels as an argument; stdin carries only the password (for sudo).
REMOTE_SCRIPT="$(cat <<'REMOTE'
set -e
read -r pw
trap 'rm -rf "$RDIR"' EXIT
exec 9>/tmp/watchdog-go2-deploy.lock
flock -n 9 || { echo "another Watch Dog deploy is running on this Orin - try again after it finishes" >&2; exit 1; }
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
# Keep the running image under a rollback tag (never prune-eligible), promote,
# then require the new service to come up healthy (HTTPS status with a live DDS
# link) or put the previous image back.
PREV="$(docker image inspect -f '{{.Id}}' watchdog-go2:latest 2>/dev/null || true)"
[ -n "$PREV" ] && docker tag "$PREV" watchdog-go2:previous
restart() {
  printf "%s\n" "$pw" | sudo -S -p "" bash -c "install -m 644 go2_service.service /etc/systemd/system/go2_service.service && systemctl daemon-reload && systemctl restart go2_service"
}
healthy() {
  for _ in $(seq 1 30); do
    # loopback, so the certificate name is not checked here; the Thor verifies it
    curl -ksf -m2 https://127.0.0.1:5001/status | grep -q '"connected":true' && return 0
    sleep 2
  done
  return 1
}
docker tag "$ID" watchdog-go2:latest
restart
if healthy; then
  echo "new service healthy ($ID)"
else
  echo "new service NOT healthy within 60s" >&2
  if [ -n "$PREV" ]; then
    docker tag "$PREV" watchdog-go2:latest && restart
    healthy && echo "rolled back to $PREV (healthy)" >&2 || echo "rolled back to $PREV - STILL NOT HEALTHY, check the robot" >&2
  fi
  exit 1
fi
REMOTE
)"
printf '%s\n' "$SSHPASS" | sshpass -e ssh "${SSH_OPTS[@]}" "$HOST" "RDIR=$(printf %q "$RDIR") bash -c $(printf %q "$REMOTE_SCRIPT")"
echo "deployed to $HOST"
