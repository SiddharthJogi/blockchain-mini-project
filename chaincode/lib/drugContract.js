'use strict';

const { Contract } = require('fabric-contract-api');

// ---------------------------------------------------------------------------
// Participants (Fabric test-network has exactly two organisations)
//   Org1MSP = the manufacturer
//   Org2MSP = every other party: distributor, wholesaler, pharmacy
// ---------------------------------------------------------------------------
const MANUFACTURER_MSP = 'Org1MSP';
const PARTNER_MSP = 'Org2MSP';

const STATUS = {
    MANUFACTURED: 'Manufactured',
    TRANSFERRED: 'Transferred',
    DISPENSED: 'Dispensed',
    RECALLED: 'Recalled'
};

const ID_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function requireText(field, value, maxLength = 100) {
    if (typeof value !== 'string' || value.trim() === '') {
        throw new Error(`${field} is required`);
    }
    const trimmed = value.trim();
    if (trimmed.length > maxLength) {
        throw new Error(`${field} must be at most ${maxLength} characters`);
    }
    return trimmed;
}

function requireDrugId(value) {
    const id = requireText('drugId', value, 64);
    if (!ID_PATTERN.test(id)) {
        throw new Error('drugId may only contain letters, digits, "_" and "-"');
    }
    return id;
}

function requireDate(field, value) {
    const text = requireText(field, value, 10);
    const parsed = new Date(`${text}T00:00:00Z`);
    if (!DATE_PATTERN.test(text) || Number.isNaN(parsed.getTime()) ||
        parsed.toISOString().slice(0, 10) !== text) {
        throw new Error(`${field} must be a valid date in YYYY-MM-DD format`);
    }
    return text;
}

function longToNumber(value) {
    if (typeof value === 'number') return value;
    if (value && typeof value.toNumber === 'function') return value.toNumber();
    return Number(value);
}

// Fabric timestamps are protobuf objects { seconds: Long, nanos: number }.
function timestampToDate(timestamp) {
    const millis = longToNumber(timestamp.seconds) * 1000 +
        Math.floor((timestamp.nanos || 0) / 1e6);
    return new Date(millis);
}

// Use the transaction timestamp (not the wall clock) so every endorsing peer
// computes exactly the same result.
function txDate(ctx) {
    return timestampToDate(ctx.stub.getTxTimestamp()).toISOString().slice(0, 10);
}

function callerOf(ctx) {
    const msp = ctx.clientIdentity.getMSPID();
    const fullId = ctx.clientIdentity.getID();
    const match = /CN=([^/:]+)/.exec(fullId);
    return { msp, name: match ? match[1] : fullId };
}

function deny(message) {
    return new Error(`Access denied: ${message}`);
}

async function collect(iterator, mapFn) {
    const results = [];
    while (true) {
        const result = await iterator.next();
        if (result.value) {
            const mapped = mapFn(result.value);
            if (mapped !== undefined) results.push(mapped);
        }
        if (result.done) {
            await iterator.close();
            break;
        }
    }
    return results;
}

class DrugContract extends Contract {

    // -----------------------------------------------------------------------
    // Internal state access
    // -----------------------------------------------------------------------

    async _load(ctx, drugId) {
        const bytes = await ctx.stub.getState(drugId);
        if (!bytes || bytes.length === 0) {
            throw new Error(`Drug ${drugId} does not exist`);
        }
        return JSON.parse(bytes.toString());
    }

    async _save(ctx, drug, action) {
        const caller = callerOf(ctx);
        drug.lastAction = action;
        drug.lastUpdatedBy = caller.name;
        drug.lastUpdatedByMSP = caller.msp;
        await ctx.stub.putState(drug.drugId, Buffer.from(JSON.stringify(drug)));
    }

    _assertNotExpired(ctx, drug) {
        if (txDate(ctx) > drug.expiryDate) {
            throw new Error(`Drug ${drug.drugId} expired on ${drug.expiryDate}`);
        }
    }

    // -----------------------------------------------------------------------
    // 1. CREATE (manufacturer only)
    // -----------------------------------------------------------------------

    async CreateDrug(ctx, drugId, drugName, batchNumber, manufacturer, manufacturingDate, expiryDate) {
        const caller = callerOf(ctx);
        if (caller.msp !== MANUFACTURER_MSP) {
            throw deny(`only the manufacturer (${MANUFACTURER_MSP}) can create drugs, caller is ${caller.msp}`);
        }

        const id = requireDrugId(drugId);
        const drug = {
            docType: 'drug',
            drugId: id,
            drugName: requireText('drugName', drugName),
            batchNumber: requireText('batchNumber', batchNumber),
            manufacturer: requireText('manufacturer', manufacturer),
            manufacturingDate: requireDate('manufacturingDate', manufacturingDate),
            expiryDate: requireDate('expiryDate', expiryDate),
            status: STATUS.MANUFACTURED
        };
        if (drug.expiryDate <= drug.manufacturingDate) {
            throw new Error('expiryDate must be later than manufacturingDate');
        }
        if (await this.DrugExists(ctx, id)) {
            throw new Error(`Drug ${id} already exists`);
        }

        drug.currentOwner = drug.manufacturer;
        drug.ownerMSP = MANUFACTURER_MSP;

        await this._save(ctx, drug, 'Created');
        return JSON.stringify(drug);
    }

    // -----------------------------------------------------------------------
    // 2. EXISTS
    // -----------------------------------------------------------------------

    async DrugExists(ctx, drugId) {
        const bytes = await ctx.stub.getState(drugId);
        return !!bytes && bytes.length > 0;
    }

    // -----------------------------------------------------------------------
    // 3. READ
    // -----------------------------------------------------------------------

    async ReadDrug(ctx, drugId) {
        const bytes = await ctx.stub.getState(drugId);
        if (!bytes || bytes.length === 0) {
            throw new Error(`Drug ${drugId} does not exist`);
        }
        return bytes.toString();
    }

    // -----------------------------------------------------------------------
    // 4. TRANSFER (only the organisation that currently holds the drug)
    // -----------------------------------------------------------------------

    async TransferDrug(ctx, drugId, newOwner) {
        const caller = callerOf(ctx);
        const drug = await this._load(ctx, requireDrugId(drugId));
        const target = requireText('newOwner', newOwner);

        if (caller.msp !== drug.ownerMSP) {
            throw deny(`${drug.drugId} is held by ${drug.currentOwner} (${drug.ownerMSP}); ` +
                `${caller.msp} cannot transfer it`);
        }
        if (drug.status !== STATUS.MANUFACTURED && drug.status !== STATUS.TRANSFERRED) {
            throw new Error(`Drug ${drug.drugId} is ${drug.status} and cannot be transferred`);
        }
        this._assertNotExpired(ctx, drug);
        if (target.toLowerCase() === drug.currentOwner.toLowerCase()) {
            throw new Error(`${target} already owns drug ${drug.drugId}`);
        }

        const previousOwner = drug.currentOwner;
        drug.currentOwner = target;
        drug.ownerMSP = PARTNER_MSP;
        drug.status = STATUS.TRANSFERRED;
        await this._save(ctx, drug, 'Transferred');

        return JSON.stringify({
            drugId: drug.drugId,
            previousOwner: previousOwner,
            newOwner: target,
            status: drug.status
        });
    }

    // -----------------------------------------------------------------------
    // 5. DISPENSE to the end customer (supply-chain partners only, final state)
    // -----------------------------------------------------------------------

    async DispenseDrug(ctx, drugId) {
        const caller = callerOf(ctx);
        const drug = await this._load(ctx, requireDrugId(drugId));

        if (caller.msp !== PARTNER_MSP || drug.ownerMSP !== PARTNER_MSP) {
            throw deny(`only the current holder (${PARTNER_MSP}) can dispense; ` +
                `${drug.drugId} is held by ${drug.ownerMSP}, caller is ${caller.msp}`);
        }
        if (drug.status !== STATUS.TRANSFERRED) {
            throw new Error(`Drug ${drug.drugId} is ${drug.status} and cannot be dispensed`);
        }
        this._assertNotExpired(ctx, drug);

        drug.status = STATUS.DISPENSED;
        await this._save(ctx, drug, 'Dispensed');
        return JSON.stringify(drug);
    }

    // -----------------------------------------------------------------------
    // 6. RECALL (original manufacturer only, any time)
    // -----------------------------------------------------------------------

    async RecallDrug(ctx, drugId, reason) {
        const caller = callerOf(ctx);
        if (caller.msp !== MANUFACTURER_MSP) {
            throw deny(`only the manufacturer (${MANUFACTURER_MSP}) can recall drugs, caller is ${caller.msp}`);
        }
        const drug = await this._load(ctx, requireDrugId(drugId));
        const why = requireText('reason', reason, 200);
        if (drug.status === STATUS.RECALLED) {
            throw new Error(`Drug ${drug.drugId} is already recalled`);
        }

        drug.status = STATUS.RECALLED;
        drug.recallReason = why;
        await this._save(ctx, drug, 'Recalled');
        return JSON.stringify(drug);
    }

    // -----------------------------------------------------------------------
    // 7. HISTORY (every change ever committed for this drug)
    // -----------------------------------------------------------------------

    async GetDrugHistory(ctx, drugId) {
        if (!(await this.DrugExists(ctx, drugId))) {
            throw new Error(`Drug ${drugId} does not exist`);
        }
        const iterator = await ctx.stub.getHistoryForKey(drugId);
        const history = await collect(iterator, (entry) => ({
            transactionId: entry.tx_id,
            timestamp: timestampToDate(entry.timestamp).toISOString(),
            isDelete: entry.is_delete,
            data: entry.is_delete ? '' : entry.value.toString('utf8')
        }));
        return JSON.stringify(history);
    }

    // -----------------------------------------------------------------------
    // 8. LIST ALL
    // -----------------------------------------------------------------------

    async GetAllDrugs(ctx) {
        const iterator = await ctx.stub.getStateByRange('', '');
        const drugs = await collect(iterator, (entry) => {
            try {
                const drug = JSON.parse(entry.value.toString('utf8'));
                return drug.docType === 'drug' ? drug : undefined;
            } catch (err) {
                return undefined;
            }
        });
        return JSON.stringify(drugs);
    }
}

module.exports = DrugContract;
