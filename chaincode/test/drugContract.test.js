'use strict';

// Runs the chaincode logic against an in-memory mock of the Fabric stub.
// Usage:  npm install && npm test

const { test, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const DrugContract = require('../lib/drugContract');

const ORG1 = 'Org1MSP'; // manufacturer
const ORG2 = 'Org2MSP'; // distributor / wholesaler / pharmacy

function iteratorOf(items) {
    let i = 0;
    return {
        next: async () => (i < items.length
            ? { value: items[i++], done: false }
            : { value: undefined, done: true }),
        close: async () => {}
    };
}

function makeLedger() {
    const state = new Map();
    const history = new Map();
    let txCounter = 0;

    // Returns a ctx for one transaction submitted by `msp` at `isoTime`.
    return function ctxFor(msp, isoTime = '2026-10-17T10:00:00Z') {
        const txId = `tx${++txCounter}`;
        const seconds = Math.floor(Date.parse(isoTime) / 1000);
        const org = msp.replace('MSP', '').toLowerCase();
        return {
            _state: state,
            clientIdentity: {
                getMSPID: () => msp,
                getID: () => `x509::/C=US/OU=admin/CN=Admin@${org}.example.com::/C=US/CN=ca.${org}.example.com`
            },
            stub: {
                getTxID: () => txId,
                getTxTimestamp: () => ({ seconds: { toNumber: () => seconds }, nanos: 0 }),
                getState: async (key) => state.get(key) || Buffer.alloc(0),
                putState: async (key, value) => {
                    state.set(key, value);
                    if (!history.has(key)) history.set(key, []);
                    history.get(key).push({
                        tx_id: txId, timestamp: { seconds, nanos: 0 }, is_delete: false, value
                    });
                },
                getHistoryForKey: async (key) => iteratorOf(history.get(key) || []),
                getStateByRange: async () => iteratorOf(
                    [...state.entries()].sort().map(([key, value]) => ({ key, value })))
            }
        };
    };
}

let contract;
let ctxFor;

beforeEach(() => {
    contract = new DrugContract();
    ctxFor = makeLedger();
});

const create = (id = 'D1', overrides = {}) => {
    const a = { name: 'Paracetamol', batch: 'B1', maker: 'ABC Pharma', mfg: '2026-01-01', exp: '2028-01-01', ...overrides };
    return contract.CreateDrug(ctxFor(ORG1), id, a.name, a.batch, a.maker, a.mfg, a.exp);
};
const read = async (id = 'D1') => JSON.parse(await contract.ReadDrug(ctxFor(ORG1), id));
const denied = /Access denied/;

// ---------------------------------------------------------------- create

test('manufacturer can create a drug and becomes its owner', async () => {
    const drug = JSON.parse(await create());
    assert.equal(drug.status, 'Manufactured');
    assert.equal(drug.currentOwner, 'ABC Pharma');
    assert.equal(drug.ownerMSP, ORG1);
    assert.equal(drug.lastUpdatedBy, 'Admin@org1.example.com');
    assert.equal(drug.lastUpdatedByMSP, ORG1);
});

test('non-manufacturer cannot create drugs (counterfeit registration)', async () => {
    await assert.rejects(
        contract.CreateDrug(ctxFor(ORG2), 'D1', 'Fake', 'B1', 'ABC Pharma', '2026-01-01', '2028-01-01'),
        denied);
    assert.equal(await contract.DrugExists(ctxFor(ORG1), 'D1'), false);
});

test('create rejects duplicates and invalid input', async () => {
    await create();
    await assert.rejects(create('D1'), /already exists/);
    await assert.rejects(create('D2', { mfg: 'not-a-date' }), /manufacturingDate must be a valid date/);
    await assert.rejects(create('D2', { exp: '2026-02-30' }), /expiryDate must be a valid date/);
    await assert.rejects(create('D2', { exp: '2026-01-01' }), /expiryDate must be later/);
    await assert.rejects(create('D2', { name: '   ' }), /drugName is required/);
    await assert.rejects(create('bad id!'), /drugId may only contain/);
});

// -------------------------------------------------------------- transfer

test('only the current holder can transfer, and only along the chain', async () => {
    await create();

    // Org2 does not hold the drug yet -> cannot steal it
    await assert.rejects(contract.TransferDrug(ctxFor(ORG2), 'D1', 'Attacker Ltd'), denied);

    // Manufacturer hands over to a distributor
    const res = JSON.parse(await contract.TransferDrug(ctxFor(ORG1), 'D1', 'XYZ Distributor'));
    assert.equal(res.previousOwner, 'ABC Pharma');
    assert.equal(res.newOwner, 'XYZ Distributor');
    let drug = await read();
    assert.equal(drug.status, 'Transferred');
    assert.equal(drug.ownerMSP, ORG2);

    // Manufacturer no longer holds it
    await assert.rejects(contract.TransferDrug(ctxFor(ORG1), 'D1', 'Somebody'), denied);

    // Partner passes it on to a pharmacy
    await contract.TransferDrug(ctxFor(ORG2), 'D1', 'City Pharmacy');
    drug = await read();
    assert.equal(drug.currentOwner, 'City Pharmacy');
    assert.equal(drug.lastUpdatedByMSP, ORG2);
});

test('transfer rejects missing drug, empty owner and same owner', async () => {
    await create();
    await assert.rejects(contract.TransferDrug(ctxFor(ORG1), 'NOPE', 'X'), /does not exist/);
    await assert.rejects(contract.TransferDrug(ctxFor(ORG1), 'D1', '  '), /newOwner is required/);
    await assert.rejects(contract.TransferDrug(ctxFor(ORG1), 'D1', 'abc pharma'), /already owns/);
});

test('expired drugs cannot be transferred or dispensed', async () => {
    await create('OLD', { mfg: '2025-01-01', exp: '2026-01-31' });
    await assert.rejects(contract.TransferDrug(ctxFor(ORG1), 'OLD', 'Dist'), /expired on 2026-01-31/);

    // Valid when transferred, but expires before it is dispensed
    await create('SOON', { mfg: '2026-01-01', exp: '2026-10-20' });
    await contract.TransferDrug(ctxFor(ORG1, '2026-10-17T10:00:00Z'), 'SOON', 'Dist');
    await assert.rejects(
        contract.DispenseDrug(ctxFor(ORG2, '2026-10-21T10:00:00Z'), 'SOON'), /expired/);
    // Expiry day itself is still fine
    await contract.DispenseDrug(ctxFor(ORG2, '2026-10-20T23:00:00Z'), 'SOON');
});

// -------------------------------------------------------------- dispense

test('dispense: only the partner holding the drug, once, as a final state', async () => {
    await create();
    await assert.rejects(contract.DispenseDrug(ctxFor(ORG2), 'D1'), denied);   // still with manufacturer
    await assert.rejects(contract.DispenseDrug(ctxFor(ORG1), 'D1'), denied);

    await contract.TransferDrug(ctxFor(ORG1), 'D1', 'City Pharmacy');
    await assert.rejects(contract.DispenseDrug(ctxFor(ORG1), 'D1'), denied);   // manufacturer cannot dispense

    const dispensed = JSON.parse(await contract.DispenseDrug(ctxFor(ORG2), 'D1'));
    assert.equal(dispensed.status, 'Dispensed');

    await assert.rejects(contract.DispenseDrug(ctxFor(ORG2), 'D1'), /cannot be dispensed/);
    await assert.rejects(contract.TransferDrug(ctxFor(ORG2), 'D1', 'Other'), /cannot be transferred/);
});

// ---------------------------------------------------------------- recall

test('recall: manufacturer only, needs a reason, blocks further movement', async () => {
    await create();
    await contract.TransferDrug(ctxFor(ORG1), 'D1', 'XYZ Distributor');

    await assert.rejects(contract.RecallDrug(ctxFor(ORG2), 'D1', 'because'), denied);
    await assert.rejects(contract.RecallDrug(ctxFor(ORG1), 'D1', ''), /reason is required/);

    const recalled = JSON.parse(await contract.RecallDrug(ctxFor(ORG1), 'D1', 'Contamination in batch'));
    assert.equal(recalled.status, 'Recalled');
    assert.equal(recalled.recallReason, 'Contamination in batch');

    await assert.rejects(contract.TransferDrug(ctxFor(ORG2), 'D1', 'Other'), /cannot be transferred/);
    await assert.rejects(contract.DispenseDrug(ctxFor(ORG2), 'D1'), /cannot be dispensed/);
    await assert.rejects(contract.RecallDrug(ctxFor(ORG1), 'D1', 'again'), /already recalled/);
});

test('the unrestricted UpdateDrug function is gone', () => {
    assert.equal(typeof contract.UpdateDrug, 'undefined');
});

// -------------------------------------------------------- read / history

test('read and exists', async () => {
    await create();
    assert.equal(await contract.DrugExists(ctxFor(ORG2), 'D1'), true);
    assert.equal(await contract.DrugExists(ctxFor(ORG2), 'D9'), false);
    await assert.rejects(contract.ReadDrug(ctxFor(ORG2), 'D9'), /does not exist/);
});

test('history lists every change in order with ISO timestamps', async () => {
    await create();
    await contract.TransferDrug(ctxFor(ORG1, '2026-10-17T11:00:00Z'), 'D1', 'XYZ Distributor');
    await contract.RecallDrug(ctxFor(ORG1, '2026-10-17T12:00:00Z'), 'D1', 'Quality issue');

    const history = JSON.parse(await contract.GetDrugHistory(ctxFor(ORG2), 'D1'));
    assert.equal(history.length, 3);
    assert.deepEqual(history.map((h) => JSON.parse(h.data).lastAction),
        ['Created', 'Transferred', 'Recalled']);
    assert.equal(history[1].timestamp, '2026-10-17T11:00:00.000Z');
    assert.ok(history.every((h) => h.transactionId && h.isDelete === false));

    await assert.rejects(contract.GetDrugHistory(ctxFor(ORG2), 'D9'), /does not exist/);
});

test('GetAllDrugs returns drugs only and skips unrelated keys', async () => {
    await create('D1');
    await create('D2', { name: 'Ibuprofen' });
    const ctx = ctxFor(ORG1);
    await ctx.stub.putState('junk', Buffer.from('not json'));
    await ctx.stub.putState('other', Buffer.from(JSON.stringify({ hello: 'world' })));

    const all = JSON.parse(await contract.GetAllDrugs(ctxFor(ORG2)));
    assert.deepEqual(all.map((d) => d.drugId), ['D1', 'D2']);
});
