// Pure tests for the Sales Invoice receivable-account helper: Frappe is stubbed, nothing touches a site.
const assert = require("node:assert/strict");
const path = require("node:path");

const APP_DIR = path.join(__dirname, "..", "..");

const registrations = [];
const calls = [];
let pending = [];
let reply = () => ({ message: "Debtors USD - SP" });

globalThis.window = globalThis;
globalThis.frappe = {
	boot: {},
	ui: { form: { on: (doctype, events) => registrations.push([doctype, events]) } },
	after_ajax: (fn) => pending.push(fn),
	call: async (opts) => {
		calls.push(opts);
		return reply(opts);
	},
};
const helper = require(path.join(APP_DIR, "public", "js", "customer_receivable_account.js"));

const tests = [];
const test = (name, run) => tests.push([name, run]);
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

function enable(value = 1) {
	frappe.boot = { smartprocess_accounting: { customer_currency_receivable_account: value } };
}

function form(values = {}, isNew = true) {
	const sets = [];
	const frm = {
		docname: "new-sales-invoice-1",
		doc: { docstatus: 0, is_return: 0, customer: "C-USD", company: "SP", debit_to: "Debtors - SP", ...values },
		is_new: () => isNew,
		async set_value(fieldname, value) {
			sets.push([fieldname, value]);
			this.doc[fieldname] = value;
		},
	};
	return { frm, sets };
}

// The controller's own request finishes first, then the helper's deferred work runs.
async function settle() {
	await tick();
	const queued = pending;
	pending = [];
	for (const fn of queued) {
		await fn();
	}
	await tick();
}

function reset() {
	calls.length = 0;
	pending = [];
	reply = () => ({ message: "Debtors USD - SP" });
}

test("1 registers customer, company and refresh on Sales Invoice once", () => {
	helper.register(frappe);
	helper.register(frappe);
	assert.deepEqual(registrations.map(([doctype]) => doctype), ["Sales Invoice"]);
	assert.deepEqual(Object.keys(registrations[0][1]).sort(), ["company", "customer", "refresh"]);
});

test("2 setting off: no request and ERPNext's debit_to stays", async () => {
	reset();
	enable(0);
	const { frm, sets } = form();
	helper.schedule(frm);
	await settle();
	assert.equal(calls.length, 0);
	assert.deepEqual(sets, []);
});

test("3 customer change sets the server's account after ERPNext's own handler", async () => {
	reset();
	enable();
	const { frm, sets } = form();
	helper.schedule(frm);
	assert.equal(calls.length, 0, "nothing is requested before ERPNext's requests settle");
	await settle();
	assert.equal(calls[0].method, helper.METHOD);
	assert.deepEqual(calls[0].args, { customer: "C-USD", company: "SP" });
	assert.deepEqual(sets, [["debit_to", "Debtors USD - SP"]]);
});

test("4 submitted, cancelled, return or incomplete invoices are left alone", async () => {
	enable();
	for (const values of [{ docstatus: 1 }, { docstatus: 2 }, { is_return: 1 }, { customer: "" }, { company: "" }]) {
		reset();
		const { frm, sets } = form(values);
		helper.schedule(frm);
		await settle();
		assert.equal(calls.length, 0, JSON.stringify(values));
		assert.deepEqual(sets, [], JSON.stringify(values));
	}
});

test("5 only the latest change wins and a changed party discards the reply", async () => {
	reset();
	enable();
	const { frm, sets } = form();
	helper.schedule(frm);
	frm.doc.company = "SP2";
	helper.schedule(frm);
	await settle();
	assert.equal(calls.length, 1);
	assert.deepEqual(calls[0].args, { customer: "C-USD", company: "SP2" });

	reset();
	reply = () => {
		frm.doc.customer = "C-OTHER";
		return { message: "Debtors USD - SP" };
	};
	sets.length = 0;
	helper.schedule(frm);
	await settle();
	assert.deepEqual(sets, [], "the reply belongs to the previous customer");
});

test("6 a server error or an empty reply never changes debit_to", async () => {
	enable();
	for (const next of [() => Promise.reject(new Error("no account")), () => ({ message: null })]) {
		reset();
		reply = next;
		const { frm, sets } = form();
		helper.schedule(frm);
		await settle();
		assert.deepEqual(sets, []);
		assert.equal(frm.doc.debit_to, "Debtors - SP");
	}
});

test("7 an already correct account is not rewritten", async () => {
	reset();
	enable();
	const { frm, sets } = form({ debit_to: "Debtors USD - SP" });
	helper.schedule(frm);
	await settle();
	assert.equal(calls.length, 1);
	assert.deepEqual(sets, []);
});

test("8 refresh fills a new invoice once, never a saved one", async () => {
	reset();
	enable();
	const fresh = form();
	helper.refresh(fresh.frm);
	helper.refresh(fresh.frm);
	await settle();
	assert.equal(calls.length, 1);
	assert.deepEqual(fresh.sets, [["debit_to", "Debtors USD - SP"]]);

	reset();
	const saved = form({}, false);
	helper.refresh(saved.frm);
	await settle();
	assert.equal(calls.length, 0);
});

(async () => {
	for (const [name, run] of tests) {
		await run();
		console.log(`ok - ${name}`);
	}
	console.log(`customer_receivable_account: ${tests.length} tests passed`);
})().catch((error) => {
	console.error(error);
	process.exitCode = 1;
});
