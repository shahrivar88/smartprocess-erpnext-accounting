// Pure tests for the Purchase Invoice central payable account: Frappe is stubbed, nothing touches a site.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const APP_DIR = path.join(__dirname, "..", "..");
const registrations = [];
const calls = [];
// ERPNext answers still in flight; frappe.after_ajax lands them before our callback.
const erpnextInFlight = [];
let reply = null;
const reads = [];
let original = null;

globalThis.window = globalThis;
globalThis.frappe = {
	boot: { smartprocess_accounting: { central_default_accounts: 1 } },
	ui: { form: { on: (doctype, events) => registrations.push([doctype, events]) } },
	call(opts) {
		calls.push(opts);
		return Promise.resolve(typeof reply === "function" ? reply(opts) : reply).then((message) => ({ message }));
	},
	after_ajax(fn) {
		while (erpnextInFlight.length) erpnextInFlight.shift()();
		return Promise.resolve(fn());
	},
	db: {
		get_value(doctype, name, fields) {
			reads.push([doctype, name, fields]);
			const answer = typeof original === "function" ? original() : original;
			return Promise.resolve(answer).then((message) => ({ message }));
		},
	},
};
const pida = require(path.join(APP_DIR, "public", "js", "purchase_invoice_default_account.js"));
const { events } = pida;

const tests = [];
const test = (name, run) => tests.push([name, run]);

function form(values = {}) {
	return {
		doc: {
			doctype: "Purchase Invoice",
			name: "new-purchase-invoice-1",
			docstatus: 0,
			is_return: 0,
			company: "A",
			supplier: "S",
			currency: "IRR",
			credit_to: "Creditors - A",
			...values,
		},
		set: [],
		set_value(fieldname, value) {
			this.set.push([fieldname, value]);
			this.doc[fieldname] = value;
			return Promise.resolve();
		},
	};
}

function reset(enabled = 1) {
	calls.length = 0;
	erpnextInFlight.length = 0;
	reads.length = 0;
	reply = "Central IRR - A";
	original = { credit_to: "Original - A", company: "A", supplier: "S", docstatus: 1, is_return: 0 };
	frappe.boot.smartprocess_accounting.central_default_accounts = enabled;
}

async function supplierFlow(frm, erpnextAccount = "Creditors - A", currency = frm.doc.currency) {
	await events.supplier(frm);
	frm.updating_party_details = true;
	frm.doc.credit_to = erpnextAccount;
	frm.doc.currency = currency;
	await events.credit_to(frm);
	await events.currency(frm);
	frm.updating_party_details = false;
	await events.refresh(frm);
}

// ERPNext's Purchase Invoice "company" handler sets Credit To; transaction.js then fires "currency".
async function companyFlow(frm, company, erpnextAccount) {
	await events.company(frm);
	frm.doc.company = company;
	frm.doc.credit_to = erpnextAccount;
	await events.credit_to(frm);
	await events.currency(frm);
}

async function centralDraft() {
	reset();
	const frm = form();
	await supplierFlow(frm);
	assert.equal(frm.doc.credit_to, "Central IRR - A");
	calls.length = 0;
	frm.set.length = 0;
	return frm;
}

function changeCurrency(frm, currency) {
	frm.doc.currency = currency;
	return events.currency(frm);
}

// Like jQuery, every handler bound to an event runs.
function withCreditToInput(frm) {
	const handlers = {};
	const bound = {};
	const data = {};
	frm.fields_dict = {
		credit_to: {
			$input: {
				data(key, value) {
					if (value === undefined) return data[key];
					data[key] = value;
					return this;
				},
				on(names, handler) {
					for (const name of names.split(" ")) {
						(bound[name] ||= []).push(handler);
						handlers[name] = () => bound[name].forEach((run) => run());
					}
					return this;
				},
			},
		},
	};
	return handlers;
}

function mappedForm(rows, values = {}) {
	return form({ __islocal: 1, __onload: { load_after_mapping: 1 }, items: rows, ...values });
}

// A new Debit Note as make_debit_note opens it: the original invoice's Credit To is already in place.
function debitNote(values = {}) {
	return mappedForm([{ purchase_invoice_item: "PII-1" }], {
		name: "new-purchase-invoice-9",
		is_return: 1,
		return_against: "PINV-1",
		credit_to: "Original - A",
		...values,
	});
}

// ERPNext's onload "company" trigger: the handler's get_party_account answer lands on Credit To.
function erpnextCompanyRefill(frm, account = "Creditors - A") {
	frm.doc.credit_to = account;
	return events.credit_to(frm);
}

test("1 registers once for Purchase Invoice only", () => {
	pida.register(frappe);
	pida.register(frappe);
	assert.deepEqual(
		registrations.map(([doctype]) => doctype),
		["Purchase Invoice"],
	);
	assert.match(pida.METHOD, /purchase_invoice_default_account\.propose_for_draft$/);
});

test("2 after ERPNext's Supplier refill the central account is proposed and set", async () => {
	reset();
	const frm = form();
	await supplierFlow(frm);
	assert.equal(calls.length, 1);
	assert.deepEqual(calls[0].args, { company: "A", supplier: "S", currency: "IRR", account: "Creditors - A" });
	assert.deepEqual(frm.set, [["credit_to", "Central IRR - A"]]);
});

test("3 a Supplier refill that also sets the currency sends one request for the final currency", async () => {
	reset();
	reply = "Central USD - A";
	const frm = form();
	await supplierFlow(frm, "Creditors - A", "USD");
	assert.equal(calls.length, 1);
	assert.equal(calls[0].args.currency, "USD");
	assert.equal(calls[0].args.previous_currency, undefined);
	assert.equal(frm.doc.credit_to, "Central USD - A");
});

test("4 inter-company and mapped invoices: ERPNext skips the Supplier refill, so do we", async () => {
	for (const values of [{ inter_company_invoice_reference: "SINV-1" }, { __onload: { load_after_mapping: 1 } }]) {
		reset();
		const frm = form(values);
		await supplierFlow(frm);
		assert.equal(calls.length, 0, JSON.stringify(values));
	}
});

test("5 a Company change is followed once: on the Credit To refill, not again on currency", async () => {
	reset();
	reply = "Central IRR - B";
	const frm = form();
	await companyFlow(frm, "B", "Creditors - B");
	assert.equal(calls.length, 1);
	assert.deepEqual(calls[0].args, { company: "B", supplier: "S", currency: "IRR", account: "Creditors - B" });
	assert.equal(frm.doc.credit_to, "Central IRR - B");
});

test("6 a mapped draft's Company change is followed: ERPNext refills Credit To there too", async () => {
	reset();
	reply = "Central IRR - B";
	const frm = form({ __onload: { load_after_mapping: 1 } });
	await events.company(frm);
	frm.doc.company = "B";
	frm.doc.credit_to = "Creditors - B";
	await events.credit_to(frm);
	assert.equal(calls.length, 1);
	assert.equal(frm.doc.credit_to, "Central IRR - B");
});

test("7 ERPNext's late Company refill with the same account still lets the proposal land", async () => {
	reset();
	const frm = form();
	reply = () => {
		erpnextInFlight.push(() => {
			frm.doc.credit_to = "Creditors - A";
		});
		return "Central IRR - A";
	};
	await supplierFlow(frm);
	assert.equal(frm.doc.credit_to, "Central IRR - A");
});

test("8 ERPNext's late refill with another account wins over the proposal", async () => {
	reset();
	const frm = form();
	reply = () => {
		erpnextInFlight.push(() => {
			frm.doc.credit_to = "Creditors (no supplier) - A";
		});
		return "Central IRR - A";
	};
	await supplierFlow(frm);
	assert.deepEqual(frm.set, []);
	assert.equal(frm.doc.credit_to, "Creditors (no supplier) - A");
});

test("9 currency changes move between the payable accounts and back", async () => {
	const frm = await centralDraft();
	reply = "Central USD - A";
	await changeCurrency(frm, "USD");
	assert.deepEqual(calls[0].args, {
		company: "A",
		supplier: "S",
		currency: "USD",
		account: "Central IRR - A",
		previous_currency: "IRR",
	});
	reply = "Central IRR - A";
	await changeCurrency(frm, "IRR");
	assert.equal(calls[1].args.previous_currency, "USD");
	assert.equal(frm.doc.credit_to, "Central IRR - A");
});

test("10 rapid currency changes: only the latest answer is applied, repeated events ask once", async () => {
	const frm = await centralDraft();
	const answers = [];
	reply = () => new Promise((resolve) => answers.push(resolve));
	const first = changeCurrency(frm, "USD");
	const second = changeCurrency(frm, "EUR");
	const repeated = events.currency(frm);
	assert.equal(calls.length, 2, "the repeated EUR event shares the request in flight");
	answers[1]("Central EUR - A");
	answers[0]("Central USD - A");
	await Promise.all([first, second, repeated]);
	assert.deepEqual(frm.set, [["credit_to", "Central EUR - A"]]);
});

test("11 a manual Credit To is kept through currency changes", async () => {
	const frm = await centralDraft();
	const handlers = withCreditToInput(frm);
	await events.refresh(frm);
	handlers["awesomplete-selectcomplete"]();
	frm.doc.credit_to = "Manual - A";
	await events.credit_to(frm);
	await changeCurrency(frm, "USD");
	assert.equal(calls.length, 0);
	assert.equal(frm.doc.credit_to, "Manual - A");
});

test("12 a manual pick during the server call wins", async () => {
	reset();
	const frm = form();
	const handlers = withCreditToInput(frm);
	await events.refresh(frm);
	reply = () => {
		handlers.input();
		return "Central IRR - A";
	};
	await supplierFlow(frm);
	assert.deepEqual(frm.set, []);
});

test("13 drafts from a Purchase Order or Purchase Receipt ask once when they open", async () => {
	const cases = [
		[[{ purchase_order: "PO-1" }], "Purchase Order"],
		[[{ purchase_receipt: "PR-1", purchase_order: "PO-1" }], "Purchase Receipt"],
	];
	for (const [rows, source] of cases) {
		reset();
		const frm = mappedForm(rows);
		await events.onload_post_render(frm);
		assert.deepEqual(calls[0].args, {
			company: "A",
			supplier: "S",
			currency: "IRR",
			account: "Creditors - A",
			mapped_from: source,
		});
		assert.equal(frm.doc.credit_to, "Central IRR - A", source);
	}
});

test("14 other mapped drafts keep their account", async () => {
	reset();
	const forms = [
		mappedForm([{}]),
		mappedForm([{ purchase_order: "PO-1" }, { purchase_receipt: "PR-1" }]),
		mappedForm([{ purchase_order: "PO-1" }], { is_return: 1 }),
		mappedForm([{ purchase_order: "PO-1" }], { __islocal: 0 }),
		mappedForm([{ purchase_order: "PO-1" }], { inter_company_invoice_reference: "SINV-1", supplier: "" }),
	];
	for (const frm of forms) {
		await events.onload_post_render(frm);
	}
	assert.equal(calls.length, 0);
});

test("15 returns, submitted invoices and a disabled feature ask nothing", async () => {
	for (const values of [{ is_return: 1 }, { docstatus: 1 }]) {
		reset();
		const frm = form(values);
		await supplierFlow(frm);
		await companyFlow(frm, "B", "Creditors - B");
		await changeCurrency(frm, "USD");
		assert.equal(calls.length, 0, JSON.stringify(values));
	}
	reset(0);
	const frm = form();
	await supplierFlow(frm);
	await companyFlow(frm, "B", "Creditors - B");
	assert.equal(calls.length, 0);
});

test("16 saving carries the automatic origin to the saved name", async () => {
	const frm = await centralDraft();
	await events.validate(frm);
	frm.doc.name = "ACC-PINV-0001";
	await events.after_save(frm);
	reply = "Central USD - A";
	await changeCurrency(frm, "USD");
	assert.equal(frm.doc.credit_to, "Central USD - A");
});

test("17 a manual edit on an earlier document of the same form does not block a mapped draft", async () => {
	reset();
	const frm = form();
	const handlers = withCreditToInput(frm);
	await events.refresh(frm);
	handlers.input();
	frm.doc = mappedForm([{ purchase_order: "PO-1" }], { name: "new-purchase-invoice-2" }).doc;
	await events.onload_post_render(frm);
	assert.equal(calls.length, 1);
	assert.equal(frm.doc.credit_to, "Central IRR - A");
});

test("18 a Debit Note gets the original Credit To back after ERPNext's Company refill", async () => {
	reset();
	const frm = debitNote();
	await events.company(frm);
	await events.onload_post_render(frm);
	await erpnextCompanyRefill(frm);
	assert.deepEqual(reads, [["Purchase Invoice", "PINV-1", ["credit_to", "company", "supplier", "docstatus", "is_return"]]]);
	assert.deepEqual(frm.set, [["credit_to", "Original - A"]]);
	assert.equal(calls.length, 0, "a return never asks for the central account");
});

test("19 the refill and the original's answer may land in either order", async () => {
	reset();
	let answer;
	original = () => new Promise((resolve) => (answer = resolve));
	const early = debitNote();
	const opening = events.refresh(early);
	const refill = erpnextCompanyRefill(early);
	answer({ credit_to: "Original - A", company: "A", supplier: "S", docstatus: 1, is_return: 0 });
	await Promise.all([opening, refill]);
	assert.equal(early.doc.credit_to, "Original - A");
	assert.equal(reads.length, 1, "one read per return");

	reset();
	const late = debitNote();
	await events.refresh(late);
	assert.deepEqual(late.set, []);
	await erpnextCompanyRefill(late);
	await events.credit_to(late);
	assert.deepEqual(late.set, [["credit_to", "Original - A"]]);
	assert.equal(reads.length, 1);
});

test("20 a manual Credit To on a Debit Note is kept; the server checks it on Submit", async () => {
	reset();
	const frm = debitNote();
	const handlers = withCreditToInput(frm);
	await events.refresh(frm);
	handlers["awesomplete-selectcomplete"]();
	frm.doc.credit_to = "Manual - A";
	await events.credit_to(frm);
	await erpnextCompanyRefill(frm, "Creditors - A");
	assert.deepEqual(frm.set, []);
});

test("21 another Company or Supplier, or an original that is not a submitted invoice, is not restored", async () => {
	const valid = { credit_to: "Original - A", company: "A", supplier: "S", docstatus: 1, is_return: 0 };
	const cases = [
		[{ company: "B" }, valid],
		[{ supplier: "S2" }, valid],
		[{}, { ...valid, docstatus: 0 }],
		[{}, { ...valid, is_return: 1 }],
		[{}, null],
		[{}, () => Promise.reject(new Error("403"))],
	];
	for (const [values, answer] of cases) {
		reset();
		original = answer;
		const frm = debitNote(values);
		await erpnextCompanyRefill(frm);
		assert.deepEqual(frm.set, [], JSON.stringify(values));
	}
});

test("22 saved, submitted and unlinked invoices never read an original", async () => {
	const forms = [
		debitNote({ __islocal: 0, name: "PINV-RET-1" }),
		debitNote({ docstatus: 1 }),
		debitNote({ return_against: "" }),
		mappedForm([{ purchase_order: "PO-1" }]),
		form(),
	];
	for (const frm of forms) {
		reset();
		await events.refresh(frm);
		await erpnextCompanyRefill(frm);
		assert.equal(reads.length, 0, frm.doc.name);
	}
});

test("23 hooks load the engine before each invoice script, and each script on its own form", () => {
	const hooks = fs.readFileSync(path.join(APP_DIR, "hooks.py"), "utf-8");
	const block = hooks.slice(hooks.indexOf("doctype_js"), hooks.indexOf("doc_events"));
	const sales = block.slice(block.indexOf('"Sales Invoice"'), block.indexOf('"Purchase Invoice"'));
	const purchase = block.slice(block.indexOf('"Purchase Invoice"'), block.indexOf('"Payment Entry"'));
	for (const [list, own, other] of [
		[sales, "sales_invoice_default_account.js", "purchase_invoice_default_account.js"],
		[purchase, "purchase_invoice_default_account.js", "sales_invoice_default_account.js"],
	]) {
		assert.ok(list.indexOf("invoice_default_account.js") < list.indexOf(own));
		assert.ok(list.includes("/invoice_default_account.js"));
		assert.ok(!list.includes(other));
	}
});

(async () => {
	for (const [name, run] of tests) {
		await run();
		console.log(`ok - ${name}`);
	}
	console.log(`purchase_invoice_default_account: ${tests.length} tests passed`);
})().catch((error) => {
	console.error(error);
	process.exitCode = 1;
});
