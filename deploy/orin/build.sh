#!/usr/bin/env bash
# Build and install the Watch Dog robot link on the dog's Orin, from the Mac.
#   deploy/orin/build.sh [unitree@<orin-ip>]
# Stages go2_service.py, this folder and the shared go2dds package at the
# revision pinned in GO2DDS_REV (exported with `git archive` from the sibling
# checkout GO2DDS_DIR, default ../go2dds - uncommitted edits there are never
# shipped), builds the image on the Orin, checks the Orin has the token and
# TLS files the unit needs, then installs the unit and restarts the service.
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
# Refuse to replace a running service with one that would fail closed.
printf '%s\n' "$SSHPASS" | sshpass -e ssh "${SSH_OPTS[@]}" "$HOST" 'read -r pw; printf "%s\n" "$pw" | sudo -S -p "" sh -c "
  grep -q \"^GO2_SERVICE_TOKEN=.\{32,\}\" /etc/go2_service.env && grep -q \"^GO2_AES_KEY=.\" /etc/go2_service.env &&
  test -s /etc/watchdog-go2/tls/cert.pem && test -s /etc/watchdog-go2/tls/key.pem"' \
  || { echo "Orin is missing /etc/go2_service.env (GO2_SERVICE_TOKEN, GO2_AES_KEY) or /etc/watchdog-go2/tls/{cert,key}.pem - see deploy/orin/README.md" >&2; exit 1; }
printf '%s\n' "$SSHPASS" | sshpass -e ssh "${SSH_OPTS[@]}" "$HOST" 'read -r pw; cd ~/watchdog-go2 && docker build -q -t watchdog-go2:latest . && \
  printf "%s\n" "$pw" | sudo -S -p "" bash -c "install -m 644 go2_service.service /etc/systemd/system/go2_service.service && systemctl daemon-reload && systemctl restart go2_service"' 
echo "deployed to $HOST"
