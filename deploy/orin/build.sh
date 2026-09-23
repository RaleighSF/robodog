#!/usr/bin/env bash
# Build and install the Watch Dog robot link on the dog's Orin, from the Mac.
#   deploy/orin/build.sh [unitree@<orin-ip>]
# Stages go2_service.py, this folder and the shared go2dds package (sibling
# checkout, GO2DDS_DIR, default ../go2dds next to this repo), builds the image
# on the Orin, installs the unit and restarts the service.
set -euo pipefail
HOST="${1:-unitree@10.0.0.57}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
GO2DDS_DIR="${GO2DDS_DIR:-$(cd "$REPO/.." && pwd)/go2dds}"
[ -f "$GO2DDS_DIR/go2dds/core.py" ] || { echo "go2dds not found at $GO2DDS_DIR" >&2; exit 1; }
: "${SSHPASS:?export SSHPASS (the Orin password) first}"
SSH_OPTS=(-o StrictHostKeyChecking=no -o IdentitiesOnly=yes -o PubkeyAuthentication=no -o LogLevel=ERROR)
STAGE="$(mktemp -d)"; trap 'rm -rf "$STAGE"' EXIT
cp "$HERE/Dockerfile" "$HERE/entrypoint.sh" "$HERE/go2_service.service" "$REPO/go2_service.py" "$STAGE/"
mkdir -p "$STAGE/go2dds" && cp "$GO2DDS_DIR"/go2dds/*.py "$STAGE/go2dds/"
sshpass -e ssh "${SSH_OPTS[@]}" "$HOST" 'rm -rf ~/watchdog-go2 && mkdir -p ~/watchdog-go2'
sshpass -e scp -r "${SSH_OPTS[@]}" "$STAGE"/* "$HOST":watchdog-go2/
printf '%s\n' "$SSHPASS" | sshpass -e ssh "${SSH_OPTS[@]}" "$HOST" 'read -r pw; cd ~/watchdog-go2 && docker build -q -t watchdog-go2:latest . && \
  printf "%s\n" "$pw" | sudo -S -p "" bash -c "install -m 644 go2_service.service /etc/systemd/system/go2_service.service && systemctl daemon-reload && systemctl restart go2_service"' 
echo "deployed to $HOST"
