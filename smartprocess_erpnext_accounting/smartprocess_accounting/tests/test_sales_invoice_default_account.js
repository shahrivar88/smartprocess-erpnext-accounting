// Pure tests for the Sales Invoice central receivable account: Frappe is stubbed, nothing touches a site.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const APP_DIR = path.join(__dirname, "..", "..");
const registrations = [];
const calls = [];
let reply = null;

globalThis.window = globalThis;
globalThis.frappe = {
	boot: { smartprocess_accounting: { central_default_accounts: 1 } },
	ui: { form: { on: (doctype, events) => registrations.push([doctype, events]) } },
	call(opts) {
		calls.push(opts);
		// A reply function may return a promise to answer later, out of order.
		return Promise.resolve(typeof reply === "function" ? reply(opts) : reply).then((message) => ({ message }));
	},
};
const sida = require(path.join(APP_DIR, "public", "js", "sales_invoice_default_account.js"));
const { events } = sida;

const tests = [];
const test = (name, run) => tests.push([name, run]);

function form(values = {}) {
	const frm = {
		doc: {
			doctype: "Sales Invoice",
			name: "new-sales-invoice-1",
			docstatus: 0,
			is_return: 0,
			company: "A",
			customer: "C",
			currency: "IRR",
			debit_to: "Debtors - A",
			...values,
		},
		set: [],
		set_value(fieldname, value) {
			this.set.push([fieldname, value]);
			this.doc[fieldname] = value;
			return Promise.resolve();
		},
	};
	return frm;
}

function reset(enabled = 1) {
	calls.length = 0;
	reply = "Central IRR - A";
	frappe.boot.smartprocess_accounting.central_default_accounts = enabled;
}

async function customerFlow(frm, erpnextAccount = "Debtors - A") {
	await events.customer(frm);
	frm.updating_party_details = true;
	frm.doc.debit_to = erpnextAccount;
	await events.customer(frm);
	frm.updating_party_details = false;
	await events.refresh(frm);
}

async function companyFlow(frm, company, erpnextAccount) {
	await events.company(frm);
	frm.doc.company = company;
	frm.doc.debit_to = erpnextAccount;
	await events.currency(frm);
}

// A draft whose Debit To holds the central IRR account picked after ERPNext's Customer refill.
async function centralDraft(values = {}) {
	reset();
	const frm = form(values);
	await customerFlow(frm);
	assert.equal(frm.doc.debit_to, "Central IRR - A");
	calls.length = 0;
	frm.set.length = 0;
	return frm;
}

function changeCurrency(frm, currency) {
	frm.doc.currency = currency;
	return events.currency(frm);
}

function mappedForm(rows, values = {}) {
	return form({ __islocal: 1, __onload: { load_after_mapping: 1 }, items: rows, ...values });
}

test("1 registers once for Sales Invoice only", () => {
	sida.register(frappe);
	sida.register(frappe);
	assert.deepEqual(
		registrations.map(([doctype]) => doctype),
		["Sales Invoice"],
	);
});

test("2 after ERPNext's Customer refill the central account is proposed and set", async () => {
	reset();
	const frm = form();
	await customerFlow(frm);
	assert.equal(calls.length, 1);
	assert.equal(calls[0].method, sida.METHOD);
	assert.deepEqual(calls[0].args, { company: "A", customer: "C", currency: "IRR", account: "Debtors - A" });
	assert.deepEqual(frm.set, [["debit_to", "Central IRR - A"]]);
});

test("3 after ERPNext's Company refill the proposal uses the new company", async () => {
	reset();
	reply = "Central IRR - B";
	const frm = form();
	await companyFlow(frm, "B", "Debtors - B");
	assert.deepEqual(calls[0].args, { company: "B", customer: "C", currency: "IRR", account: "Debtors - B" });
	assert.deepEqual(frm.set, [["debit_to", "Central IRR - B"]]);
});

test("4 a server answer of null keeps ERPNext's account", async () => {
	reset();
	reply = null;
	const frm = form();
	await customerFlow(frm);
	assert.equal(calls.length, 1);
	assert.deepEqual(frm.set, []);
});

test("5 disabled: no server call and no change", async () => {
	reset(0);
	const frm = form();
	await customerFlow(frm);
	await companyFlow(frm, "B", "Debtors - B");
	assert.equal(calls.length, 0);
	assert.deepEqual(frm.set, []);
});

test("6 returns and submitted invoices are left alone", async () => {
	for (const values of [{ is_return: 1 }, { docstatus: 1 }]) {
		reset();
		const frm = form(values);
		await customerFlow(frm);
		await companyFlow(frm, "B", "Debtors - B");
		assert.equal(calls.length, 0, JSON.stringify(values));
		assert.deepEqual(frm.set, []);
	}
});

test("7 a refresh or currency change without a preceding refill does nothing", async () => {
	reset();
	const frm = form();
	await events.refresh(frm);
	await events.currency(frm);
	assert.equal(calls.length, 0);
});

test("8 a manual Debit To change during the server call wins", async () => {
	reset();
	const frm = form();
	reply = () => {
		frm.doc.debit_to = "Manual - A";
		return "Central IRR - A";
	};
	await customerFlow(frm);
	assert.equal(calls.length, 1);
	assert.deepEqual(frm.set, []);
	assert.equal(frm.doc.debit_to, "Manual - A");
});

function withDebitToInput(frm) {
	const handlers = {};
	const data = {};
	frm.fields_dict = {
		debit_to: {
			$input: {
				data(key, value) {
					if (value === undefined) return data[key];
					data[key] = value;
					return this;
				},
				on(names, handler) {
					for (const name of names.split(" ")) handlers[name] = handler;
					return this;
				},
			},
		},
	};
	return handlers;
}

test("9 a manual edit of the Debit To input cancels a pending follow-up", async () => {
	reset();
	const frm = form();
	const handlers = withDebitToInput(frm);
	await events.refresh(frm);
	await events.refresh(frm);
	assert.deepEqual(Object.keys(handlers).sort(), ["awesomplete-selectcomplete", "input"]);
	await events.company(frm);
	handlers.input();
	frm.doc.company = "B";
	await events.currency(frm);
	assert.equal(calls.length, 0);
});

test("10 ERPNext's early returns are mirrored: mapped documents get no follow-up", async () => {
	reset();
	const mapped = form({ __onload: { load_after_mapping: 1 } });
	await customerFlow(mapped);
	await companyFlow(mapped, "B", "Debtors - B");
	assert.equal(calls.length, 0);
});

test("11 a Company change with an empty mapped Debit To is followed, like ERPNext refills it", async () => {
	reset();
	const frm = form({ __onload: { load_after_mapping: 1 }, debit_to: "" });
	await companyFlow(frm, "B", "Debtors - B");
	assert.equal(calls.length, 1);
});

test("12 saving drops a pending follow-up", async () => {
	reset();
	const frm = form();
	await events.company(frm);
	await events.validate(frm);
	await events.currency(frm);
	assert.equal(calls.length, 0);
});

test("13 the follow-up runs once per refill", async () => {
	reset();
	const frm = form();
	await customerFlow(frm);
	await events.refresh(frm);
	assert.equal(calls.length, 1);
});

test("14 a manual pick of the same account during the server call wins", async () => {
	reset();
	const frm = form();
	const handlers = withDebitToInput(frm);
	await events.refresh(frm);
	reply = () => {
		handlers["awesomplete-selectcomplete"]();
		return "Central IRR - A";
	};
	await customerFlow(frm);
	assert.equal(calls.length, 1);
	assert.deepEqual(frm.set, []);
	assert.equal(frm.doc.debit_to, "Debtors - A");
});

test("15 a currency change under an automatic account asks for the new currency's account", async () => {
	const frm = await centralDraft();
	reply = "Central USD - A";
	await changeCurrency(frm, "USD");
	assert.deepEqual(calls[0].args, {
		company: "A",
		customer: "C",
		currency: "USD",
		account: "Central IRR - A",
		previous_currency: "IRR",
	});
	assert.deepEqual(frm.set, [["debit_to", "Central USD - A"]]);

	reply = "Central IRR - A";
	await changeCurrency(frm, "IRR");
	assert.equal(calls[1].args.previous_currency, "USD");
	assert.equal(calls[1].args.account, "Central USD - A");
	assert.equal(frm.doc.debit_to, "Central IRR - A");
});

test("16 a currency change keeps a manual account and asks nothing", async () => {
	const frm = await centralDraft();
	const handlers = withDebitToInput(frm);
	await events.refresh(frm);
	handlers["awesomplete-selectcomplete"]();
	frm.doc.debit_to = "Manual - A";
	await events.debit_to(frm);
	await changeCurrency(frm, "USD");
	assert.equal(calls.length, 0);
	assert.equal(frm.doc.debit_to, "Manual - A");
});

test("17 a Debit To set by other code is not treated as automatic", async () => {
	const frm = await centralDraft();
	frm.doc.debit_to = "Other Script - A";
	await events.debit_to(frm);
	await changeCurrency(frm, "USD");
	assert.equal(calls.length, 0);
});

test("18 no valid account for the new currency keeps Debit To and its origin", async () => {
	const frm = await centralDraft();
	reply = null;
	await changeCurrency(frm, "EUR");
	assert.equal(frm.doc.debit_to, "Central IRR - A");
	assert.deepEqual(frm.set, []);
	await changeCurrency(frm, "IRR");
	assert.equal(calls.length, 1, "back in the account's currency: nothing to ask");
	reply = "Central USD - A";
	await changeCurrency(frm, "USD");
	assert.equal(calls[1].args.previous_currency, "IRR");
	assert.equal(frm.doc.debit_to, "Central USD - A");
});

test("19 rapid currency changes: only the answer to the latest request is applied", async () => {
	const frm = await centralDraft();
	const answers = [];
	reply = () => new Promise((resolve) => answers.push(resolve));
	const first = changeCurrency(frm, "USD");
	const second = changeCurrency(frm, "EUR");
	assert.equal(calls.length, 2);
	answers[1]("Central EUR - A");
	await second;
	answers[0]("Central USD - A");
	await first;
	assert.deepEqual(frm.set, [["debit_to", "Central EUR - A"]]);
});

test("20 a late answer for a currency already changed back is dropped", async () => {
	const frm = await centralDraft();
	const answers = [];
	reply = () => new Promise((resolve) => answers.push(resolve));
	const pending = changeCurrency(frm, "USD");
	await changeCurrency(frm, "IRR");
	answers[0]("Central USD - A");
	await pending;
	assert.equal(calls.length, 1);
	assert.deepEqual(frm.set, []);
	assert.equal(frm.doc.debit_to, "Central IRR - A");
});

test("21 the currency events of ERPNext's own refills send no extra request", async () => {
	reset();
	const frm = form();
	await events.customer(frm);
	frm.updating_party_details = true;
	frm.doc.debit_to = "Debtors - A";
	frm.doc.currency = "USD";
	await events.debit_to(frm);
	await events.currency(frm);
	frm.updating_party_details = false;
	await events.refresh(frm);
	assert.equal(calls.length, 1);
	assert.equal(calls[0].args.previous_currency, undefined);
});

test("22 a stale Company mark over a central account still names the previous currency", async () => {
	const frm = await centralDraft();
	await events.company(frm);
	reply = "Central USD - A";
	await changeCurrency(frm, "USD");
	assert.equal(calls.length, 1);
	assert.equal(calls[0].args.previous_currency, "IRR");
	assert.equal(frm.doc.debit_to, "Central USD - A");
});

test("23 returns and submitted invoices ignore currency changes", async () => {
	for (const values of [{ is_return: 1 }, { docstatus: 1 }]) {
		const frm = await centralDraft();
		Object.assign(frm.doc, values);
		await changeCurrency(frm, "USD");
		assert.equal(calls.length, 0, JSON.stringify(values));
		assert.equal(frm.doc.debit_to, "Central IRR - A");
	}
});

test("24 a draft made from a Sales Order or Delivery Note asks once when it opens", async () => {
	const cases = [
		[[{ sales_order: "SO-1" }, { sales_order: "SO-2" }], "Sales Order"],
		[[{ delivery_note: "DN-1", sales_order: "SO-1" }], "Delivery Note"],
	];
	for (const [rows, source] of cases) {
		reset();
		const frm = mappedForm(rows);
		await events.onload_post_render(frm);
		assert.deepEqual(calls[0].args, {
			company: "A",
			customer: "C",
			currency: "IRR",
			account: "Debtors - A",
			mapped_from: source,
		});
		assert.deepEqual(frm.set, [["debit_to", "Central IRR - A"]]);
		reply = "Central USD - A";
		await changeCurrency(frm, "USD");
		assert.equal(frm.doc.debit_to, "Central USD - A", source);
	}
});

test("25 other mapped drafts keep the copied account", async () => {
	const forms = [
		mappedForm([{ sales_order: "SO-1" }, { delivery_note: "DN-1" }]),
		mappedForm([{ sales_order: "SO-1" }, {}]),
		mappedForm([]),
		mappedForm([{ sales_order: "SO-1" }], { is_pos: 1 }),
		mappedForm([{ sales_order: "SO-1" }], { is_return: 1 }),
		mappedForm([{ sales_order: "SO-1" }], { __islocal: 0 }),
		form({ __islocal: 1, items: [{ sales_order: "SO-1" }] }),
	];
	const edited = mappedForm([{ sales_order: "SO-1" }]);
	forms.push(edited);
	reset();
	for (const frm of forms) {
		const handlers = withDebitToInput(frm);
		await events.refresh(frm);
		if (frm === edited) handlers.input();
		await events.onload_post_render(frm);
	}
	assert.equal(calls.length, 0);
});

test("26 saving carries the automatic origin to the saved name", async () => {
	const frm = await centralDraft();
	await events.validate(frm);
	frm.doc.name = "ACC-SINV-0001";
	await events.after_save(frm);
	reply = "Central USD - A";
	await changeCurrency(frm, "USD");
	assert.equal(calls.length, 1);
	assert.equal(frm.doc.debit_to, "Central USD - A");
});

test("27 another document in the same form does not inherit the origin", async () => {
	const frm = await centralDraft();
	frm.doc = { ...frm.doc, name: "ACC-SINV-0002" };
	await changeCurrency(frm, "USD");
	assert.equal(calls.length, 0);
});

test("28 a manual edit on an earlier document of the same form does not block a mapped draft", async () => {
	reset();
	const frm = form();
	const handlers = withDebitToInput(frm);
	await events.refresh(frm);
	handlers.input();
	frm.doc = mappedForm([{ sales_order: "SO-1" }], { name: "new-sales-invoice-2" }).doc;
	await events.onload_post_render(frm);
	assert.equal(calls.length, 1);
	assert.deepEqual(frm.set, [["debit_to", "Central IRR - A"]]);
});

test("29 hooks load the script for Sales Invoice only", () => {
	const hooks = fs.readFileSync(path.join(APP_DIR, "hooks.py"), "utf-8");
	const block = hooks.slice(hooks.indexOf("doctype_js"), hooks.indexOf("doc_events"));
	const salesInvoice = block.slice(block.indexOf('"Sales Invoice"'), block.indexOf('"Purchase Invoice"'));
	assert.ok(salesInvoice.includes("sales_invoice_default_account.js"));
	assert.ok(!block.slice(block.indexOf('"Purchase Invoice"')).includes("sales_invoice_default_account.js"));
});

(async () => {
	for (const [name, run] of tests) {
		await run();
		console.log(`ok - ${name}`);
	}
	console.log(`sales_invoice_default_account: ${tests.length} tests passed`);
})().catch((error) => {
	console.error(error);
	process.exitCode = 1;
});
