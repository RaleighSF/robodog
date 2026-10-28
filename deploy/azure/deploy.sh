#!/usr/bin/env bash
# Create the Ignite ingest resources and write the Thor's send-only connection
# string to ./secrets/eventhub.conn (gitignored). Copy that file to the Thor's
# state volume as /state/eventhub.conn - never commit it.
#   az login            (you, interactively)
#   az account set -s <subscription>
#   deploy/azure/deploy.sh [resource-group] [location]
set -euo pipefail
RG="${1:-rg-watchdog-ignite}"
LOC="${2:-eastus}"
HERE="$(cd "$(dirname "$0")" && pwd)"
SUB="$(az account show --query name -o tsv)"
echo "subscription: $SUB | resource group: $RG | region: $LOC"
az group create -n "$RG" -l "$LOC" -o none
# Namespace names are global; derive a stable unique one from the subscription id.
NS="watchdog-ignite-$(az account show --query id -o tsv | cut -c1-8)"
az deployment group create -g "$RG" -n watchdog-ingest -f "$HERE/main.bicep" \
  -p namespaceName="$NS" -o table
mkdir -p "$HERE/secrets" && chmod 700 "$HERE/secrets"
az eventhubs eventhub authorization-rule keys list -g "$RG" --namespace-name "$NS" \
  --eventhub-name watchdog-telemetry -n edge-send --query primaryConnectionString -o tsv \
  > "$HERE/secrets/eventhub.conn"
chmod 600 "$HERE/secrets/eventhub.conn"
echo "send-only connection string -> $HERE/secrets/eventhub.conn (copy to the Thor's /state/eventhub.conn)"
echo "next: create the ADX free cluster, run adx/setup.kql, then connect Event Hub '$NS/watchdog-telemetry' (rule adx-listen)"
