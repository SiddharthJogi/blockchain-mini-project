# 💊 Blockchain Drug Traceability System

A pharmaceutical supply-chain tracker built on **Hyperledger Fabric**. Every change to a drug
(created, transferred, dispensed, recalled) is a ledger transaction, and the chaincode decides
**who is allowed** to make it.

| Part | Tech | Folder |
|------|------|--------|
| Smart contract (chaincode) | Node.js, `fabric-contract-api` | `chaincode/` |
| Web dashboard | Python, Streamlit | `Dashboard/` |
| Network | Docker, Fabric `test-network` (2 orgs) | started by `scripts/setup.sh` |

## Who can do what

The Fabric test-network has two organisations, used as follows:

| Organisation | Role | Allowed actions |
|--------------|------|-----------------|
| **Org1** | Manufacturer | `CreateDrug`, `RecallDrug`, transfer a drug it still holds |
| **Org2** | Distributor / wholesaler / pharmacy | transfer a drug it holds, `DispenseDrug` |

Rules enforced inside the chaincode (not just in the UI):

- Only Org1 can register or recall a drug. Org2 cannot register fakes.
- Only the organisation that currently holds a drug can transfer it. Nobody can grab or reassign someone else's stock.
- Lifecycle: `Manufactured → Transferred → Dispensed`. `Recalled` can be set by Org1 at any time. Dispensed or recalled drugs cannot move again.
- Expired drugs cannot be transferred or dispensed.
- Inputs are validated (required fields, real `YYYY-MM-DD` dates, expiry after manufacture).
- Every record stores who last changed it (`lastAction`, `lastUpdatedBy`, `lastUpdatedByMSP`), and `GetDrugHistory` returns the full audit trail.

## Setup (Linux, macOS, or Windows via WSL2)

**Prerequisites:** Docker (running), Git, curl, Python 3.9+, Node.js 18+ (only for the chaincode tests).

**1. Install Fabric** (once). Run this in your home folder so `~/fabric-samples` is created:

```bash
cd ~
curl -sSLO https://raw.githubusercontent.com/hyperledger/fabric/main/scripts/install-fabric.sh
chmod +x install-fabric.sh
./install-fabric.sh --fabric-version 2.5.9 docker samples binary
```

**2. Start the network and deploy the chaincode:**

```bash
./scripts/setup.sh
```

If `fabric-samples` is somewhere else: `export FABRIC_SAMPLES=/path/to/fabric-samples` first.

**3. Run the dashboard:**

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
streamlit run Dashboard/app.py
```

## Demo

**Terminal walkthrough (most reliable on stage):** `./scripts/demo.sh` runs the full supply chain
and includes the attempts that must be rejected.

**Dashboard walkthrough:** use the *Acting as* switch in the sidebar.

1. As **Org2**, try *Create* → rejected (only the manufacturer can register drugs).
2. As **Org1**, create `DRUG001`.
3. As **Org2**, try *Transfer* on `DRUG001` → rejected (it still belongs to Org1).
4. As **Org1**, transfer it to "XYZ Distributor".
5. As **Org1**, try to transfer it again → rejected (no longer the holder).
6. As **Org2**, transfer to "City Pharmacy", then *Dispense*.
7. Open *History* to show every step with timestamps, transaction IDs and who did it.
8. Optional: create a drug with a past expiry date and show that it cannot be transferred. Or recall one as Org1.

## Tests

```bash
cd chaincode && npm install && npm test      # 12 tests, in-memory mock of the Fabric stub
cd Dashboard && python -m unittest -v        # 8 tests, fake `peer` binary
```

These need no running network. They check the logic, not a live Fabric deployment.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| *Could not find the 'peer' binary* | Set `FABRIC_SAMPLES` to your fabric-samples folder |
| *Endorsement failure*, *channel not found*, or odd errors after a restart | Run `./scripts/setup.sh` again (it resets everything) |
| Ports already in use | `cd ~/fabric-samples/test-network && ./network.sh down` |
| Docker permission denied | Add your user to the `docker` group, or use `sudo` for Docker only |
| Edited the chaincode | Re-run `./scripts/setup.sh` to redeploy it |

## Known limitations (good to mention in your report)

- The dashboard signs requests with each organisation's **admin** identity, which is fine for a demo. A real system would give every user their own certificate and use the Fabric Gateway SDK instead of the CLI.
- Org2 stands for several parties, so owner names after the first transfer are free text, and any Org2 member can act for any Org2-held drug.
- Drugs are tracked one ID at a time. Real pharma tracking works on batches and serialised units.
- `test-network` is for learning: one peer per org, a single orderer, no production security.
