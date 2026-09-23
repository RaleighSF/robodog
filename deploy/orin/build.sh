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
sshpass -e ssh "${SSH_OPTS[@]}" "$HOST" 'rm -rf ~/watchdog-go2 && mkdir -p ~/watchdog-go2'
sshpass -e scp -r "${SSH_OPTS[@]}" "$STAGE"/* "$HOST":watchdog-go2/
# Build, then run the NEW image's --preflight with exactly the environment the
# unit will get (systemd-run applies EnvironmentFile= with systemd's own parsing)
# and the same TLS mount. Only if the service's own rules accept the token and
# can load the certificate/key pair is the running service replaced.
printf '%s\n' "$SSHPASS" | sshpass -e ssh "${SSH_OPTS[@]}" "$HOST" 'read -r pw; set -e; cd ~/watchdog-go2
  docker build -q -t watchdog-go2:candidate .
  if ! printf "%s\n" "$pw" | sudo -S -p "" systemd-run --quiet --wait --pipe --collect \
        -p EnvironmentFile=/etc/go2_service.env \
        /usr/bin/docker run --rm -e GO2_AES_KEY -e GO2_SERVICE_TOKEN \
          -e GO2_TLS_CERT=/tls/cert.pem -e GO2_TLS_KEY=/tls/key.pem \
          -v /etc/watchdog-go2/tls:/tls:ro watchdog-go2:candidate --preflight; then
    echo "preflight failed - running service left untouched (see deploy/orin/README.md)" >&2; exit 1
  fi
  docker tag watchdog-go2:candidate watchdog-go2:latest
  printf "%s\n" "$pw" | sudo -S -p "" bash -c "install -m 644 go2_service.service /etc/systemd/system/go2_service.service && systemctl daemon-reload && systemctl restart go2_service"'
echo "deployed to $HOST"
