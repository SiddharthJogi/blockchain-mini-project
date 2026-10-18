"""Streamlit dashboard for the Hyperledger Fabric drug traceability demo.

Run from the project root:   streamlit run Dashboard/app.py
"""

import json
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import fabric_client as fabric

st.set_page_config(page_title="Drug Traceability System", page_icon="💊", layout="wide")


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def parse_json(text, default=None):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return default


def show_error(result, headline):
    st.error(headline)
    st.code(result.output)
    if result.raw and result.raw != result.output:
        with st.expander("Raw Fabric output"):
            st.code(result.raw)


def show_write_result(result, success_message):
    """Show the outcome of an invoke (write) transaction."""
    if not result.ok:
        show_error(result, "Transaction rejected.")
        return
    st.success(success_message)
    payload = parse_json(result.output)
    if payload is not None:
        st.json(payload)


def require(values):
    """True when every (label, value) pair is filled in; warns about the first gap."""
    for label, value in values:
        if not value:
            st.warning(f"Please enter the {label}.")
            return False
    return True


# ----------------------------------------------------------------------------
# Sidebar: who is acting?
# ----------------------------------------------------------------------------

with st.sidebar:
    st.header("🔐 Acting as")
    org_key = st.radio(
        "Organisation",
        list(fabric.ORGS),
        format_func=lambda key: fabric.ORGS[key].label,
        label_visibility="collapsed",
    )
    org = fabric.ORGS[org_key]
    st.caption(f"Every request below is signed by the admin of **{org.msp_id}**. "
               "The chaincode decides what this organisation may do.")

    st.markdown(
        "**Rules enforced by the chaincode**\n"
        "- Only Org1 can create or recall a drug\n"
        "- Only the organisation currently holding a drug can transfer it\n"
        "- Only Org2 can dispense, and only after a transfer\n"
        "- Expired, recalled or dispensed drugs cannot move"
    )

    if st.button("Check network connection"):
        status = fabric.channel_status(org)
        if status.ok:
            st.success(f"Peer reachable. {status.output}")
        else:
            st.error(status.output)


# ----------------------------------------------------------------------------
# Header
# ----------------------------------------------------------------------------

st.title("💊 Drug Traceability System")
st.markdown("### Hyperledger Fabric blockchain dashboard")
st.markdown("Track a drug from **manufacturer → distributor → pharmacy → customer**, "
            "with every change recorded on the ledger.")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Channel", fabric.CHANNEL)
col2.metric("Chaincode", fabric.CHAINCODE)
col3.metric("Network", "Hyperledger Fabric")
col4.metric("Acting as", org.msp_id)
st.divider()

tabs = st.tabs([
    "➕ Create", "🔎 Exists", "📄 Read", "🚚 Transfer",
    "💊 Dispense", "⚠️ Recall", "📜 History", "📦 All Drugs",
])

# ----------------------------------------------------------------------------
# Create (manufacturer only)
# ----------------------------------------------------------------------------

with tabs[0]:
    st.header("Create New Drug")
    st.caption("Allowed for Org1 (manufacturer). Try it as Org2 to see the chaincode reject it.")

    drug_id = st.text_input("Drug ID", placeholder="DRUG001", key="create_id")
    drug_name = st.text_input("Drug Name", placeholder="Paracetamol", key="create_name")
    batch_number = st.text_input("Batch Number", placeholder="BATCH001", key="create_batch")
    manufacturer = st.text_input("Manufacturer", placeholder="ABC Pharma", key="create_maker")
    manufacturing_date = st.date_input("Manufacturing Date", value=date.today(), key="create_mfg")
    expiry_date = st.date_input("Expiry Date", value=date.today() + timedelta(days=730), key="create_exp")

    if st.button("Create Drug", type="primary", key="create_btn"):
        drug_id, drug_name = drug_id.strip(), drug_name.strip()
        batch_number, manufacturer = batch_number.strip(), manufacturer.strip()
        if require([("Drug ID", drug_id), ("Drug Name", drug_name),
                    ("Batch Number", batch_number), ("Manufacturer", manufacturer)]):
            if expiry_date <= manufacturing_date:
                st.warning("Expiry Date must be later than Manufacturing Date.")
            else:
                result = fabric.invoke(org, "CreateDrug", drug_id, drug_name, batch_number,
                                       manufacturer, manufacturing_date.isoformat(),
                                       expiry_date.isoformat())
                show_write_result(result, "Drug created on the blockchain.")

# ----------------------------------------------------------------------------
# Exists
# ----------------------------------------------------------------------------

with tabs[1]:
    st.header("Check Drug Existence")
    exists_id = st.text_input("Drug ID", placeholder="DRUG001", key="exists_id").strip()
    if st.button("Check Drug", type="primary", key="exists_btn") and require([("Drug ID", exists_id)]):
        result = fabric.query(org, "DrugExists", exists_id)
        if not result.ok:
            show_error(result, "Query failed.")
        elif result.output.lower() == "true":
            st.success(f"Drug {exists_id} exists on the blockchain.")
        else:
            st.error(f"Drug {exists_id} does not exist.")

# ----------------------------------------------------------------------------
# Read
# ----------------------------------------------------------------------------

with tabs[2]:
    st.header("Read Drug Information")
    read_id = st.text_input("Drug ID", placeholder="DRUG001", key="read_id").strip()
    if st.button("Read Drug", type="primary", key="read_btn") and require([("Drug ID", read_id)]):
        result = fabric.query(org, "ReadDrug", read_id)
        if not result.ok:
            show_error(result, "Drug not found.")
        else:
            st.success("Drug information retrieved.")
            st.json(parse_json(result.output, default=result.output))

# ----------------------------------------------------------------------------
# Transfer
# ----------------------------------------------------------------------------

with tabs[3]:
    st.header("Transfer Drug Ownership")
    st.caption("Only the organisation that currently holds the drug can transfer it.")
    transfer_id = st.text_input("Drug ID", placeholder="DRUG001", key="transfer_id").strip()
    new_owner = st.text_input("New Owner", placeholder="XYZ Distributor", key="transfer_owner").strip()
    if st.button("Transfer Drug", type="primary", key="transfer_btn") and require(
            [("Drug ID", transfer_id), ("New Owner", new_owner)]):
        result = fabric.invoke(org, "TransferDrug", transfer_id, new_owner)
        show_write_result(result, "Drug ownership transferred.")

# ----------------------------------------------------------------------------
# Dispense
# ----------------------------------------------------------------------------

with tabs[4]:
    st.header("Dispense Drug to Customer")
    st.caption("Final step. Org2 only, and only for a drug it currently holds.")
    dispense_id = st.text_input("Drug ID", placeholder="DRUG001", key="dispense_id").strip()
    if st.button("Dispense Drug", type="primary", key="dispense_btn") and require([("Drug ID", dispense_id)]):
        result = fabric.invoke(org, "DispenseDrug", dispense_id)
        show_write_result(result, "Drug dispensed. It cannot move again.")

# ----------------------------------------------------------------------------
# Recall
# ----------------------------------------------------------------------------

with tabs[5]:
    st.header("Recall Drug")
    st.caption("Org1 (the manufacturer) only. A recalled drug cannot be transferred or dispensed.")
    recall_id = st.text_input("Drug ID", placeholder="DRUG001", key="recall_id").strip()
    recall_reason = st.text_input("Reason", placeholder="Contamination found in batch", key="recall_reason").strip()
    if st.button("Recall Drug", type="primary", key="recall_btn") and require(
            [("Drug ID", recall_id), ("Reason", recall_reason)]):
        result = fabric.invoke(org, "RecallDrug", recall_id, recall_reason)
        show_write_result(result, "Drug recalled.")

# ----------------------------------------------------------------------------
# History
# ----------------------------------------------------------------------------

with tabs[6]:
    st.header("Drug Transaction History")
    history_id = st.text_input("Drug ID", placeholder="DRUG001", key="history_id").strip()
    if st.button("View History", type="primary", key="history_btn") and require([("Drug ID", history_id)]):
        result = fabric.query(org, "GetDrugHistory", history_id)
        history = parse_json(result.output) if result.ok else None
        if not result.ok:
            show_error(result, "Could not retrieve history.")
        elif not isinstance(history, list):
            st.code(result.output)
        else:
            st.success(f"{len(history)} blockchain transaction(s) found.")
            rows = []
            for index, entry in enumerate(history, start=1):
                data = parse_json(entry.get("data"), default={}) or {}
                rows.append({
                    "#": index,
                    "Timestamp (UTC)": entry.get("timestamp", ""),
                    "Action": data.get("lastAction", ""),
                    "Done by": f"{data.get('lastUpdatedBy', '')} ({data.get('lastUpdatedByMSP', '')})",
                    "Owner": data.get("currentOwner", ""),
                    "Status": data.get("status", ""),
                    "Transaction ID": entry.get("transactionId", ""),
                })
            st.dataframe(pd.DataFrame(rows), hide_index=True)

# ----------------------------------------------------------------------------
# All drugs
# ----------------------------------------------------------------------------

with tabs[7]:
    st.header("All Drugs")
    if st.button("Load All Drugs", type="primary", key="all_btn"):
        result = fabric.query(org, "GetAllDrugs")
        drugs = parse_json(result.output) if result.ok else None
        if not result.ok:
            show_error(result, "Could not retrieve drugs.")
        elif not isinstance(drugs, list) or not drugs:
            st.info("No drugs found on the blockchain.")
        else:
            st.success(f"{len(drugs)} drug(s) found.")
            columns = ["drugId", "drugName", "batchNumber", "manufacturer", "currentOwner",
                       "status", "expiryDate", "lastAction", "lastUpdatedBy"]
            frame = pd.DataFrame(drugs).reindex(columns=columns)
            st.dataframe(frame, hide_index=True)
