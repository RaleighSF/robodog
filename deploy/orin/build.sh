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
cp "$HERE/Dockerfile" "$HERE/entrypoint.sh" "$HERE/go2_service.service" "$HERE/remote-deploy.sh" "$REPO/go2_service.py" "$STAGE/"
git -C "$GO2DDS_DIR" archive "$REV" go2dds | tar -x -C "$STAGE"
echo "$REV" > "$STAGE/go2dds/REVISION"
CA_PEM="${WATCHDOG_CA_PEM:-$HOME/.watchdog-ca/ca.pem}"   # public CA cert only, never the key
[ -f "$CA_PEM" ] || { echo "demo CA certificate not found at $CA_PEM" >&2; exit 1; }
cp "$CA_PEM" "$STAGE/ca.pem"
# Private staging dir per deploy on the Orin (no shared mutable paths).
# Stale dirs from interrupted deploys are swept on the Orin under the deploy lock.
RDIR="$(sshpass -e ssh "${SSH_OPTS[@]}" "$HOST" 'mktemp -d "$HOME/watchdog-go2.XXXXXX"')"
# From allocation on, this side removes it too (covers scp/ssh/password failures).
trap 'rm -rf "$STAGE"; sshpass -e ssh "${SSH_OPTS[@]}" "$HOST" "rm -rf $(printf %q "$RDIR")" 2>/dev/null || true' EXIT
sshpass -e scp -r "${SSH_OPTS[@]}" "$STAGE"/* "$HOST":"$RDIR"/
# Build, then run THAT image's --preflight (by image ID, never a shared tag)
# with exactly the environment the unit will get (systemd-run applies
# EnvironmentFile= with systemd's own parsing) and the same TLS mount; promote
# the same ID only if it passes. The whole step is serialized by a lock, so a
# concurrent deploy fails fast instead of interleaving.
# stdin carries only the password (for sudo); the steps are in remote-deploy.sh.
printf '%s\n' "$SSHPASS" | sshpass -e ssh "${SSH_OPTS[@]}" "$HOST" "RDIR=$(printf %q "$RDIR") bash $(printf %q "$RDIR")/remote-deploy.sh"
echo "deployed to $HOST"
