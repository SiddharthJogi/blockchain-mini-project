"""Tests for fabric_client.py using a fake `peer` binary (no Fabric network needed).

Run from the Dashboard folder:   python -m unittest -v
"""

import json
import os
import stat
import tempfile
import textwrap
import unittest

# The fake fabric-samples tree must exist before fabric_client is imported,
# because the module reads FABRIC_SAMPLES at import time.
_TMP = tempfile.TemporaryDirectory()
SAMPLES = os.path.join(_TMP.name, "fabric-samples")
LOG = os.path.join(_TMP.name, "peer-calls.jsonl")
os.makedirs(os.path.join(SAMPLES, "bin"))
os.makedirs(os.path.join(SAMPLES, "test-network"))
os.environ["FABRIC_SAMPLES"] = SAMPLES
os.environ["FAKE_PEER_LOG"] = LOG

FAKE_PEER = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, sys

    argv = sys.argv[1:]
    call = {"argv": argv, "msp": os.environ.get("CORE_PEER_LOCALMSPID"),
            "address": os.environ.get("CORE_PEER_ADDRESS"),
            "mspconfig": os.environ.get("CORE_PEER_MSPCONFIGPATH")}
    with open(os.environ["FAKE_PEER_LOG"], "a") as log:
        log.write(json.dumps(call) + "\\n")

    if argv[:2] == ["channel", "list"]:
        print("Channels peers has joined:\\nmychannel")
        sys.exit(0)

    mode = argv[1]                       # "query" or "invoke"
    spec = json.loads(argv[argv.index("-c") + 1])
    function, args = spec["function"], spec["Args"]

    if mode == "query":
        if function == "DrugExists":
            print("true" if args[0] == "D1" else "false")
        elif function == "ReadDrug" and args[0] == "MISSING":
            sys.stderr.write('Error: endorsement failure during query. response: status:500 '
                             'message:"Drug MISSING does not exist"\\n')
            sys.exit(1)
        else:
            print(json.dumps({"drugId": args[0] if args else None}))
        sys.exit(0)

    if function == "CreateDrug" and os.environ["CORE_PEER_LOCALMSPID"] != "Org1MSP":
        sys.stderr.write('Error: endorsement failure during invoke. response: status:500 message:'
                         '"transaction returned with failure: Error: Access denied: only the '
                         'manufacturer (Org1MSP) can create drugs, caller is Org2MSP"\\n')
        sys.exit(1)
    payload = json.dumps({"drugId": args[0], "status": "Manufactured"})
    sys.stderr.write("2026-10-17 10:00:00.000 IST 0001 INFO [chaincodeCmd] chaincodeInvokeOrQuery "
                     "-> Chaincode invoke successful. result: status:200 payload:"
                     + json.dumps(payload) + "\\n")
''')

peer_path = os.path.join(SAMPLES, "bin", "peer")
with open(peer_path, "w") as handle:
    handle.write(FAKE_PEER)
os.chmod(peer_path, os.stat(peer_path).st_mode | stat.S_IEXEC)

import fabric_client as fabric  # noqa: E402  (must come after the setup above)


def calls():
    with open(LOG) as handle:
        return [json.loads(line) for line in handle if line.strip()]


class FabricClientTests(unittest.TestCase):

    def setUp(self):
        if os.path.exists(LOG):
            os.remove(LOG)

    def test_environment_targets_the_selected_org(self):
        env = fabric.fabric_environment(fabric.ORG2)
        self.assertEqual(env["CORE_PEER_LOCALMSPID"], "Org2MSP")
        self.assertEqual(env["CORE_PEER_ADDRESS"], "localhost:9051")
        self.assertTrue(env["CORE_PEER_MSPCONFIGPATH"].endswith("Admin@org2.example.com/msp"))
        self.assertTrue(env["CORE_PEER_TLS_ROOTCERT_FILE"].endswith("peer0.org2.example.com/tls/ca.crt"))
        self.assertTrue(env["PATH"].startswith(os.path.join(SAMPLES, "bin")))

    def test_query_returns_stdout(self):
        self.assertEqual(fabric.query(fabric.ORG1, "DrugExists", "D1").output, "true")
        self.assertEqual(fabric.query(fabric.ORG2, "DrugExists", "D9").output, "false")
        # Queries run as the chosen org and never go through the orderer
        first, second = calls()
        self.assertEqual((first["msp"], second["msp"]), ("Org1MSP", "Org2MSP"))
        self.assertNotIn("-o", first["argv"])

    def test_query_error_is_readable(self):
        result = fabric.query(fabric.ORG1, "ReadDrug", "MISSING")
        self.assertFalse(result.ok)
        self.assertEqual(result.output, "Drug MISSING does not exist")

    def test_invoke_success_returns_payload_and_uses_both_endorsers(self):
        result = fabric.invoke(fabric.ORG1, "CreateDrug", "D1", "Paracetamol", "B1",
                               "ABC Pharma", "2026-01-01", "2028-01-01")
        self.assertTrue(result.ok)
        self.assertEqual(json.loads(result.output), {"drugId": "D1", "status": "Manufactured"})

        argv = calls()[0]["argv"]
        self.assertEqual(argv[:2], ["chaincode", "invoke"])
        self.assertEqual(argv.count("--peerAddresses"), 2)
        self.assertIn("localhost:7051", argv)
        self.assertIn("localhost:9051", argv)
        self.assertEqual(argv[argv.index("-o") + 1], "localhost:7050")
        self.assertEqual(argv[argv.index("-C") + 1], "mychannel")
        self.assertEqual(argv[argv.index("-n") + 1], "drug")

    def test_chaincode_access_denied_is_surfaced(self):
        result = fabric.invoke(fabric.ORG2, "CreateDrug", "D1", "x", "x", "x", "2026-01-01", "2028-01-01")
        self.assertFalse(result.ok)
        self.assertTrue(result.output.startswith("Access denied: only the manufacturer"))
        self.assertEqual(calls()[0]["msp"], "Org2MSP")

    def test_arguments_with_quotes_survive_intact(self):
        tricky = 'O"Brien\'s; rm -rf / $(whoami) \u00e9'
        fabric.invoke(fabric.ORG1, "TransferDrug", "D1", tricky)
        argv = calls()[0]["argv"]
        spec = json.loads(argv[argv.index("-c") + 1])
        self.assertEqual(spec, {"function": "TransferDrug", "Args": ["D1", tricky]})

    def test_missing_peer_binary_gives_a_helpful_message(self):
        result = fabric._run(["definitely-not-a-real-binary"], fabric.ORG1, parse_stdout=True)
        self.assertFalse(result.ok)
        self.assertIn("FABRIC_SAMPLES", result.output)

    def test_channel_status(self):
        result = fabric.channel_status(fabric.ORG1)
        self.assertTrue(result.ok)
        self.assertIn("mychannel", result.output)


if __name__ == "__main__":
    unittest.main()
