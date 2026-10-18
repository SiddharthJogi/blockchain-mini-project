"""Thin wrapper around the Hyperledger Fabric `peer` CLI (fabric-samples test-network).

Configuration (all optional, via environment variables):
    FABRIC_SAMPLES    path to your fabric-samples folder   (default: ~/fabric-samples)
    FABRIC_CHANNEL    channel name                         (default: mychannel)
    FABRIC_CHAINCODE  chaincode name                       (default: drug)
"""

import json
import os
import re
import subprocess
from dataclasses import dataclass

CHANNEL = os.environ.get("FABRIC_CHANNEL", "mychannel")
CHAINCODE = os.environ.get("FABRIC_CHAINCODE", "drug")
FABRIC_SAMPLES = os.path.expanduser(os.environ.get("FABRIC_SAMPLES", "~/fabric-samples"))
TIMEOUT_SECONDS = 60

TEST_NETWORK = os.path.join(FABRIC_SAMPLES, "test-network")
FABRIC_BIN = os.path.join(FABRIC_SAMPLES, "bin")
FABRIC_CONFIG = os.path.join(FABRIC_SAMPLES, "config")
ORG_DIR = os.path.join(TEST_NETWORK, "organizations")

ORDERER_ADDRESS = "localhost:7050"
ORDERER_HOST = "orderer.example.com"
ORDERER_CA = os.path.join(
    ORG_DIR, "ordererOrganizations", "example.com", "orderers",
    "orderer.example.com", "msp", "tlscacerts", "tlsca.example.com-cert.pem",
)


@dataclass(frozen=True)
class Org:
    key: str
    label: str
    msp_id: str
    domain: str
    port: int

    @property
    def peer_address(self):
        return f"localhost:{self.port}"

    @property
    def tls_cert(self):
        return os.path.join(ORG_DIR, "peerOrganizations", self.domain,
                            "peers", f"peer0.{self.domain}", "tls", "ca.crt")

    @property
    def admin_msp(self):
        return os.path.join(ORG_DIR, "peerOrganizations", self.domain,
                            "users", f"Admin@{self.domain}", "msp")


ORG1 = Org("Org1", "Org1 - Manufacturer", "Org1MSP", "org1.example.com", 7051)
ORG2 = Org("Org2", "Org2 - Distributor / Pharmacy", "Org2MSP", "org2.example.com", 9051)
ORGS = {ORG1.key: ORG1, ORG2.key: ORG2}


@dataclass(frozen=True)
class Result:
    ok: bool
    output: str      # payload on success, readable error message on failure
    raw: str = ""    # untouched CLI output, handy for debugging


def fabric_environment(org):
    """Environment that makes the `peer` CLI act as the admin of `org`."""
    env = os.environ.copy()
    env["PATH"] = FABRIC_BIN + os.pathsep + env.get("PATH", "")
    env["FABRIC_CFG_PATH"] = FABRIC_CONFIG
    env["CORE_PEER_TLS_ENABLED"] = "true"
    env["CORE_PEER_LOCALMSPID"] = org.msp_id
    env["CORE_PEER_TLS_ROOTCERT_FILE"] = org.tls_cert
    env["CORE_PEER_MSPCONFIGPATH"] = org.admin_msp
    env["CORE_PEER_ADDRESS"] = org.peer_address
    return env


def _unquote(text):
    """Decode a Go-quoted string such as "{\\"a\\":1}" returned by the peer CLI."""
    try:
        return json.loads(text)
    except ValueError:
        return text.strip('"')


def _error_message(stderr):
    """Pull the chaincode error text out of the peer CLI's error output."""
    match = re.search(r'message:(".*")', stderr)
    message = _unquote(match.group(1)) if match else stderr.strip()
    for prefix in ("transaction returned with failure: ", "Error: "):
        if message.startswith(prefix):
            message = message[len(prefix):]
    return message or "Unknown Fabric error"


def _invoke_payload(stderr):
    """`peer chaincode invoke` reports the return value in its log output (stderr)."""
    match = re.search(r'Chaincode invoke successful\. result: status:\d+(?: payload:(".*"))?', stderr)
    if match and match.group(1):
        return _unquote(match.group(1))
    return ""


def _run(command, org, parse_stdout):
    try:
        proc = subprocess.run(
            command, cwd=TEST_NETWORK if os.path.isdir(TEST_NETWORK) else None,
            env=fabric_environment(org), capture_output=True, text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return Result(False, "Could not find the 'peer' binary. Set FABRIC_SAMPLES to your "
                             f"fabric-samples folder (currently: {FABRIC_SAMPLES}).")
    except subprocess.TimeoutExpired:
        return Result(False, "Fabric command timed out. Is the network running?")

    raw = (proc.stdout + proc.stderr).strip()
    if proc.returncode != 0:
        return Result(False, _error_message(proc.stderr or proc.stdout), raw)
    if parse_stdout:
        return Result(True, proc.stdout.strip(), raw)
    return Result(True, _invoke_payload(proc.stderr), raw)


def _chaincode_args(function, args):
    return json.dumps({"function": function, "Args": [str(a) for a in args]})


def query(org, function, *args):
    """Read-only call, answered by the org's own peer (nothing is written)."""
    command = ["peer", "chaincode", "query", "-C", CHANNEL, "-n", CHAINCODE,
               "-c", _chaincode_args(function, args)]
    return _run(command, org, parse_stdout=True)


def invoke(org, function, *args):
    """Write transaction, endorsed by both organisations' peers and ordered."""
    command = [
        "peer", "chaincode", "invoke",
        "-o", ORDERER_ADDRESS, "--ordererTLSHostnameOverride", ORDERER_HOST,
        "--tls", "--cafile", ORDERER_CA,
        "-C", CHANNEL, "-n", CHAINCODE,
        "--peerAddresses", ORG1.peer_address, "--tlsRootCertFiles", ORG1.tls_cert,
        "--peerAddresses", ORG2.peer_address, "--tlsRootCertFiles", ORG2.tls_cert,
        "-c", _chaincode_args(function, args),
    ]
    return _run(command, org, parse_stdout=False)


def channel_status(org):
    """Quick connectivity check: which channels has this org's peer joined?"""
    return _run(["peer", "channel", "list"], org, parse_stdout=True)
