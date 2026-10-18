#!/usr/bin/env bash
# Terminal walkthrough of the whole supply chain, including the attempts that must be rejected.
# Run it after ./scripts/setup.sh. Re-running is fine: it uses a fresh drug ID each time.
set -uo pipefail

FABRIC_SAMPLES="${FABRIC_SAMPLES:-$HOME/fabric-samples}"
CHANNEL="${FABRIC_CHANNEL:-mychannel}"
CHAINCODE="${FABRIC_CHAINCODE:-drug}"
NET="$FABRIC_SAMPLES/test-network"
ORGS="$NET/organizations"

export PATH="$FABRIC_SAMPLES/bin:$PATH"
export FABRIC_CFG_PATH="$FABRIC_SAMPLES/config"
export CORE_PEER_TLS_ENABLED=true

ORDERER_CA="$ORGS/ordererOrganizations/example.com/orderers/orderer.example.com/msp/tlscacerts/tlsca.example.com-cert.pem"
ORG1_TLS="$ORGS/peerOrganizations/org1.example.com/peers/peer0.org1.example.com/tls/ca.crt"
ORG2_TLS="$ORGS/peerOrganizations/org2.example.com/peers/peer0.org2.example.com/tls/ca.crt"

as_org1() {
  export CORE_PEER_LOCALMSPID=Org1MSP CORE_PEER_ADDRESS=localhost:7051
  export CORE_PEER_TLS_ROOTCERT_FILE="$ORG1_TLS"
  export CORE_PEER_MSPCONFIGPATH="$ORGS/peerOrganizations/org1.example.com/users/Admin@org1.example.com/msp"
}
as_org2() {
  export CORE_PEER_LOCALMSPID=Org2MSP CORE_PEER_ADDRESS=localhost:9051
  export CORE_PEER_TLS_ROOTCERT_FILE="$ORG2_TLS"
  export CORE_PEER_MSPCONFIGPATH="$ORGS/peerOrganizations/org2.example.com/users/Admin@org2.example.com/msp"
}

invoke() {   # invoke <function> <arg>...   (uses the currently selected org)
  local fn="$1"; shift
  local args; args=$(printf '"%s",' "$@"); args="[${args%,}]"
  peer chaincode invoke -o localhost:7050 --ordererTLSHostnameOverride orderer.example.com \
    --tls --cafile "$ORDERER_CA" -C "$CHANNEL" -n "$CHAINCODE" \
    --peerAddresses localhost:7051 --tlsRootCertFiles "$ORG1_TLS" \
    --peerAddresses localhost:9051 --tlsRootCertFiles "$ORG2_TLS" \
    -c "{\"function\":\"$fn\",\"Args\":$args}" 2>&1 | grep -E "Chaincode invoke successful|Error" | sed -E 's/^.*(Chaincode invoke successful)/\1/; s/^Error: //'
}
query() {
  local fn="$1"; shift
  local args; args=$(printf '"%s",' "$@"); args="[${args%,}]"
  peer chaincode query -C "$CHANNEL" -n "$CHAINCODE" -c "{\"function\":\"$fn\",\"Args\":$args}" 2>&1 | sed -E 's/^Error: //'
}
step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

ID="DRUG$(date +%H%M%S)"
echo "Using drug ID: $ID"

step "1. Org2 tries to register a drug (must be REJECTED: only the manufacturer may)"
as_org2; invoke CreateDrug "$ID" "Paracetamol" "BATCH001" "ABC Pharma" "2026-01-01" "2028-01-01"

step "2. Org1 (manufacturer) creates the drug"
as_org1; invoke CreateDrug "$ID" "Paracetamol" "BATCH001" "ABC Pharma" "2026-01-01" "2028-01-01"
sleep 2; query ReadDrug "$ID"

step "3. Org2 tries to take the drug before it was handed over (must be REJECTED)"
as_org2; invoke TransferDrug "$ID" "Attacker Ltd"

step "4. Org1 transfers it to a distributor"
as_org1; invoke TransferDrug "$ID" "XYZ Distributor"
sleep 2

step "5. Org1 tries to transfer again after handing over (must be REJECTED)"
as_org1; invoke TransferDrug "$ID" "Somebody Else"

step "6. Org2 passes it on to a pharmacy, then dispenses it"
as_org2; invoke TransferDrug "$ID" "City Pharmacy"; sleep 2
invoke DispenseDrug "$ID"; sleep 2

step "7. Dispensed drugs cannot move again (must be REJECTED)"
as_org2; invoke TransferDrug "$ID" "Anyone"

step "8. Full audit trail"
query GetDrugHistory "$ID"
echo
