import sys
import os

sys.path.insert(0, os.path.abspath("Dashboard"))
import fabric_client as f

print("=== Org1 Channel Status ===")
print(f.channel_status(f.ORG1).output)

print("\n=== Org2 Channel Status ===")
print(f.channel_status(f.ORG2).output)

print("\n=== Current Drugs on Ledger ===")
result = f.query(f.ORG1, "GetAllDrugs")
print("OK:", result.ok)
print("Data:", result.output)
