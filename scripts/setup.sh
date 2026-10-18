#!/usr/bin/env bash
# Starts the Fabric test-network, creates "mychannel" and deploys the chaincode as "drug".
# Safe to re-run: it tears the old network down first (all ledger data is wiped).
#
# Usage:  ./scripts/setup.sh
# Needs:  Docker running, and fabric-samples installed (see README, step 1).
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FABRIC_SAMPLES="${FABRIC_SAMPLES:-$HOME/fabric-samples}"
CHANNEL="${FABRIC_CHANNEL:-mychannel}"
CHAINCODE="${FABRIC_CHAINCODE:-drug}"

if [ ! -x "$FABRIC_SAMPLES/test-network/network.sh" ]; then
  echo "ERROR: $FABRIC_SAMPLES/test-network/network.sh not found."
  echo "Install fabric-samples first, or point FABRIC_SAMPLES at it (see README, step 1)."
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker is not running (or your user cannot access it)."
  exit 1
fi

cd "$FABRIC_SAMPLES/test-network"

echo "==> Resetting any previous network"
./network.sh down

echo "==> Starting network and creating channel '$CHANNEL'"
./network.sh up createChannel -c "$CHANNEL"

# Fabric's test-network scripts do not handle paths with spaces.
# Stage the chaincode to a spaceless temporary directory before packaging.
STAGE_DIR="/tmp/drug-traceability-chaincode"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"
cp -r "$PROJECT_DIR/chaincode/." "$STAGE_DIR/"
rm -rf "$STAGE_DIR/node_modules"

echo "==> Deploying chaincode '$CHAINCODE' from $STAGE_DIR"
./network.sh deployCC -c "$CHANNEL" -ccn "$CHAINCODE" -ccp "$STAGE_DIR" -ccl javascript

echo
echo "Done. Next:"
echo "  ./scripts/demo.sh                      # scripted walkthrough in the terminal"
echo "  streamlit run Dashboard/app.py         # web dashboard"
