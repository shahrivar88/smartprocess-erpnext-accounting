// Pure Receipt UI tests: Frappe is stubbed, nothing touches a site.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const DOCTYPE_DIR = path.join(__dirname, "..", "doctype", "smartprocess_accounting_document");
const RECEIPT_DIR = path.join(DOCTYPE_DIR, "receipt");
const APP_DIR = path.join(__dirname, "..", "..");
const MODULES = {
	spReceiptConfig: "receipt_config.js",
	spReceiptNumbers: "receipt_numbers.js",
	spReceiptForm: "receipt_form.js",
	spReceiptHeader: "receipt_header.js",
	spReceiptRowQueries: "receipt_row_queries.js",
	spReceiptRowEvents: "receipt_row_events.js",
	spReceiptValidation: "receipt_validation_ui.js",
	spReceiptSummary: "receipt_summary.js",
};

const calls = { xcall: [], msgprint: [], setValue: [] };
let responses = {};
const docs = new Map();

globalThis.window = globalThis;
globalThis.__ = (text, args = []) => text.replace(/\{(\d+)\}/g, (_, index) => args[index]);
globalThis.frappe = {
	validated: true,
	xcall(method, args) {
		calls.xcall.push({ method, args });
		const response = responses[method.split(".").pop()];
		return Promise.resolve(typeof response === "function" ? response(args) : response);
	},
	msgprint(options) {
		calls.msgprint.push(options);
	},
	get_doc(doctype, name) {
		return docs.get(name);
	},
	model: {
		can_write: () => true,
		can_create: () => true,
		async set_value(doctype, name, fieldname, value) {
			calls.setValue.push({ name, fieldname, value });
			docs.get(name)[fieldname] = value;
		},
		clear_doc(doctype, name) {
			const row = docs.get(name);
			const parent = docs.get(row.parent);
			parent.operational_pairs = parent.operational_pairs.filter((candidate) => candidate.name !== name);
		},
	},
	meta: { docfield_map: {}, get_docfield: () => null, get_field_currency: () => null },
	form: { get_formatter: () => (value) => String(value) },
	utils: { escape_html: (value) => String(value).replace(/</g, "&lt;") },
};
for (const [name, file] of Object.entries(MODULES)) {
	globalThis[name] = require(path.join(RECEIPT_DIR, file));
}

function row(name, values = {}) {
	const value = { doctype: "SmartProcess Accounting Pair", name, parent: "new-receipt", ...values };
	docs.set(name, value);
	return value;
}

function form(values = {}, rows = []) {
	const doc = {
		doctype: "SmartProcess Accounting Document",
		name: "new-receipt",
		operation_type: "Receipt",
		docstatus: 0,
		company: "SP",
		company_currency: "IRR",
		receipt_payer_currency: "IRR",
		receipt_receiver_kind: "بانک",
		operational_pairs: rows,
		...values,
	};
	docs.set(doc.name, doc);
	const frm = {
		doc,
		docname: doc.name,
		doctype: doc.doctype,
		fields_dict: { receipt_payer_currency: { df: {} }, receipt_summary: { $wrapper: { html() {} } } },
		set_df_property() {},
		refresh_field() {},
		async set_value(fieldname, value) {
			calls.setValue.push({ name: doc.name, fieldname, value });
			doc[fieldname] = value;
		},
	};
	spReceiptForm.state(frm);
	forms.push(frm);
	return frm;
}

const forms = [];

function reset() {
	for (const frm of forms) {
		clearTimeout(spReceiptForm.state(frm).previewTimer);
	}
	calls.xcall = [];
	calls.msgprint = [];
	calls.setValue = [];
	responses = {};
	frappe.validated = true;
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));
const tests = [];
const test = (name, run) => tests.push([name, run]);
const read = (file) => fs.readFileSync(file, "utf-8");
const moduleSources = Object.values(MODULES).map((file) => read(path.join(RECEIPT_DIR, file)));
const formSource = read(path.join(DOCTYPE_DIR, "smartprocess_accounting_document.js"));
const clientSource = [formSource, ...moduleSources].join("\n");
const evalDepends = (expression, doc, parent = doc) =>
	new Function("doc", "parent", `return ${expression.replace(/^eval:/, "")}`)(doc, parent);
const gridProperty = (fieldname, property) =>
	spReceiptForm.receiptGridProperties().filter(([field, prop]) => field === fieldname && prop === property).pop()?.[2];
const docMeta = JSON.parse(read(path.join(DOCTYPE_DIR, "smartprocess_accounting_document.json")));
const pairMeta = JSON.parse(read(path.join(DOCTYPE_DIR, "..", "smartprocess_accounting_pair", "smartprocess_accounting_pair.json")));
const docField = (fieldname) => docMeta.fields.find((field) => field.fieldname === fieldname);
const pairField = (fieldname) => pairMeta.fields.find((field) => field.fieldname === fieldname);

test("1 currency defaults from Company and never overwrites a populated Receipt", async () => {
	const frm = form({ receipt_payer_currency: "", company_currency: "EUR" });
	await spReceiptHeader.applyDefaultCurrency(frm, false);
	assert.equal(frm.doc.receipt_payer_currency, "EUR");
	const populated = form({ receipt_payer_currency: "USD", receipt_payer_account: "Bank USD" });
	await spReceiptHeader.applyDefaultCurrency(populated, true);
	assert.equal(populated.doc.receipt_payer_currency, "USD");
	const empty = form({ receipt_payer_currency: "USD" });
	await spReceiptHeader.applyDefaultCurrency(empty, true);
	assert.equal(empty.doc.receipt_payer_currency, "IRR");
	assert.equal(docField("receipt_payer_currency").label, "ارز دریافت‌کننده");
	assert.ok(!/"IRR"/.test(clientSource));
});

test("2 receiver query respects the Receipt currency", () => {
	const doc = { operation_type: "Receipt", company: "SP", receipt_payer_currency: "USD", receipt_payer_type: "Customer", receipt_receiver_kind: "Customer" };
	assert.deepEqual(spReceiptHeader.receiverPartyQuery(doc).filters, { party_type: "Customer", company: "SP", currency: "USD" });
	assert.deepEqual(spReceiptHeader.receiverAccountFilters(doc), {
		company: "SP", disabled: 0, is_group: 0, account_currency: "USD", account_type: "Receivable",
	});
	assert.equal(spReceiptHeader.receiverAccountFilters({ ...doc, receipt_receiver_kind: "صندوق" }).account_type, "Cash");
});

test("3 Bank receiver lists matching Bank Accounts and fills the linked ledger", async () => {
	reset();
	const doc = { company: "SP", receipt_payer_currency: "USD" };
	assert.deepEqual(spReceiptHeader.bankAccountQuery(doc), {
		query: "smartprocess_erpnext_accounting.smartprocess_accounting.v2_api.bank_account_query",
		filters: { company: "SP", currency: "USD" },
	});
	responses.get_bank_account_details = { account: "Bank USD - SP", account_currency: "USD" };
	const frm = form({ receipt_payer_currency: "USD", receipt_bank_account: "Saman USD" });
	await spReceiptHeader.bankChanged(frm);
	assert.equal(frm.doc.receipt_payer_account, "Bank USD - SP");
	responses.get_bank_account_details = { account: "Bank IRR - SP", account_currency: "IRR" };
	await spReceiptHeader.bankChanged(frm);
	assert.equal(frm.doc.receipt_payer_account, "");
});

test("4 row Party query uses the row currency, not the Receiver currency", () => {
	const doc = { operation_type: "Receipt", company: "SP", receipt_payer_currency: "EUR" };
	assert.deepEqual(spReceiptRowQueries.payerQuery(doc, { receipt_recipient_type: "Supplier", receipt_currency: "USD" }).filters, {
		party_type: "Supplier", company: "SP", currency: "USD",
	});
	assert.deepEqual(spReceiptRowQueries.payerQuery(doc, { receipt_recipient_type: "Bank Account", receipt_currency: "IRR" }).filters, {
		company: "SP", currency: "IRR",
	});
});

test("5 row Account query uses the row currency", () => {
	const doc = { company: "SP", receipt_payer_currency: "EUR" };
	const filters = (type) => spReceiptRowQueries.payerAccountFilters(doc, { receipt_recipient_type: type, receipt_currency: "USD" });
	assert.equal(filters("Customer").account_currency, "USD");
	assert.equal(spReceiptRowQueries.payerAccountFilters(doc, { receipt_recipient_type: "Customer" }).account_currency, "");
	assert.equal(filters("Customer").account_type, "Receivable");
	assert.equal(filters("Employee").account_type, "Payable");
	assert.equal(filters("Bank Account").account_type, "Bank");
	assert.deepEqual(filters("Account").account_type, ["not in", ["Receivable", "Payable"]]);
	assert.deepEqual([filters("Account").disabled, filters("Account").is_group], [0, 0]);
});

test("6 each row has its own visible Payer Currency", async () => {
	reset();
	const currency = pairField("receipt_currency");
	assert.deepEqual([currency.hidden, currency.read_only, currency.in_list_view, currency.columns], [undefined, undefined, 1, 1]);
	assert.equal(gridProperty("receipt_currency", "hidden"), 0);
	assert.equal(gridProperty("receipt_currency", "reqd"), 1);
	assert.ok(/receipt_currency\(frm, cdt, cdn\)/.test(formSource));
	const fresh = row("row-c1", {});
	const frm = form({ receipt_payer_currency: "USD", company_currency: "IRR" }, [fresh]);
	await spReceiptRowEvents.applyDefaults(frm, fresh);
	assert.deepEqual([fresh.receipt_currency, fresh.credit_exchange_rate], ["IRR", 1]);
	const chosen = row("row-c2", { receipt_currency: "EUR", credit_exchange_rate: 900000 });
	await spReceiptRowEvents.applyDefaults(form({}, [chosen]), chosen);
	assert.deepEqual([chosen.receipt_currency, chosen.credit_exchange_rate], ["EUR", 900000]);
});

test("7 row rate: base is 1 and read-only, foreign is editable and kept", async () => {
	reset();
	assert.equal(gridProperty("credit_exchange_rate", "hidden"), 0);
	const readOnly = gridProperty("credit_exchange_rate", "read_only_depends_on");
	const parent = { company_currency: "IRR" };
	assert.equal(Boolean(evalDepends(readOnly, { receipt_currency: "IRR" }, parent)), true);
	assert.equal(Boolean(evalDepends(readOnly, { receipt_currency: "USD" }, parent)), false);
	assert.equal(gridProperty("credit_company_amount", "read_only"), 1);
	const foreign = row("row-r1", { receipt_currency: "USD", credit_exchange_rate: 1600000 });
	const base = row("row-r2", { receipt_currency: "IRR", credit_exchange_rate: 5 });
	const frm = form({}, [foreign, base]);
	await spReceiptRowEvents.rateChanged(frm, foreign.doctype, foreign.name);
	await spReceiptRowEvents.rateChanged(frm, base.doctype, base.name);
	assert.deepEqual([foreign.credit_exchange_rate, base.credit_exchange_rate], [1600000, 1]);
	assert.equal(spReceiptSummary.payload({ operational_pairs: [foreign] }).operational_pairs[0].credit_exchange_rate, 1600000);
});

test("7b row currency change resets that row's payer, ledger and stale rate only", async () => {
	reset();
	const changed = row("row-x1", { receipt_currency: "EUR", credit_exchange_rate: 1600000, receipt_recipient_type: "Customer", receipt_recipient: "C1", credit_account: "Debtors USD" });
	const other = row("row-x2", { receipt_currency: "USD", credit_exchange_rate: 1600000, receipt_recipient: "C2", credit_account: "Debtors USD" });
	const frm = form({ receipt_payer_currency: "IRR" }, [changed, other]);
	await spReceiptRowEvents.currencyChanged(frm, changed.doctype, changed.name);
	assert.deepEqual([changed.receipt_recipient, changed.credit_account, changed.credit_exchange_rate], ["", "", null]);
	assert.deepEqual([other.receipt_recipient, other.credit_account, other.credit_exchange_rate], ["C2", "Debtors USD", 1600000]);
	changed.receipt_currency = "IRR";
	await spReceiptRowEvents.currencyChanged(frm, changed.doctype, changed.name);
	assert.equal(changed.credit_exchange_rate, 1);
});

test("7c Add Row copies the previous row's currency and rate", async () => {
	reset();
	responses.get_receipt_recipient_type_default = "Customer";
	responses.get_receipt_recipient_type_options = [];
	const first = row("row-a1", { receipt_currency: "USD", credit_exchange_rate: 1600000, receipt_recipient_type: "Customer" });
	const second = row("row-a2", {});
	const frm = form({}, [first, second]);
	await spReceiptRowEvents.rowAdded(frm, second.doctype, second.name);
	assert.deepEqual([second.receipt_currency, second.credit_exchange_rate], ["USD", 1600000]);
});

test("7d Receiver currency change keeps every row currency and payer", async () => {
	reset();
	const first = row("row-h1", { receipt_currency: "USD", credit_exchange_rate: 1600000, receipt_recipient: "C1", credit_account: "Debtors USD" });
	const frm = form({ receipt_payer_currency: "EUR", receipt_payer_account: "Bank IRR" }, [first]);
	spReceiptForm.state(frm).currency = "IRR";
	await spReceiptHeader.currencyChanged(frm);
	assert.deepEqual([first.receipt_currency, first.credit_exchange_rate, first.receipt_recipient, first.credit_account], ["USD", 1600000, "C1", "Debtors USD"]);
	assert.equal(frm.doc.receipt_payer_account, "");
});

test("8 base currency rate is 1", async () => {
	const frm = form({ receipt_payer_currency: "IRR", receipt_payer_exchange_rate: 7 });
	await spReceiptHeader.normalizeRate(frm, false);
	assert.equal(frm.doc.receipt_payer_exchange_rate, 1);
	const rate = docField("receipt_payer_exchange_rate");
	assert.equal(evalDepends(rate.read_only_depends_on, frm.doc), true);
});

test("9 foreign currency requires a header rate", async () => {
	const rate = docField("receipt_payer_exchange_rate");
	const foreign = { operation_type: "Receipt", receipt_payer_currency: "USD", company_currency: "IRR" };
	assert.equal(Boolean(evalDepends(rate.mandatory_depends_on, foreign)), true);
	assert.equal(Boolean(evalDepends(rate.mandatory_depends_on, { ...foreign, receipt_payer_currency: "IRR" })), false);
	const frm = form({ receipt_payer_currency: "USD", receipt_payer_exchange_rate: 1 });
	await spReceiptHeader.normalizeRate(frm, true);
	assert.equal(frm.doc.receipt_payer_exchange_rate, null);
});

test("10 field changes never show a popup", async () => {
	reset();
	responses.get_bank_account_details = { account: "", account_currency: "EUR" };
	responses.get_receipt_party_account_suggestion = null;
	responses.preview_receipt = { ready: false, issues: [{ row: 1, field: "credit_amount", message: "x" }] };
	const first = row("row-1", { receipt_currency: "EUR", receipt_recipient_type: "Customer", receipt_recipient: "C1" });
	const frm = form({ receipt_payer_currency: "USD", receipt_bank_account: "B" }, [first]);
	spReceiptForm.state(frm).currency = "IRR";
	await spReceiptHeader.currencyChanged(frm);
	await spReceiptHeader.receiverKindChanged(frm);
	await spReceiptHeader.bankChanged(frm);
	await spReceiptHeader.partyChanged(frm);
	await spReceiptHeader.rateChanged(frm);
	await spReceiptRowEvents.currencyChanged(frm, first.doctype, first.name);
	await spReceiptRowEvents.rateChanged(frm, first.doctype, first.name);
	await spReceiptRowEvents.payerTypeChanged(frm, first.doctype, first.name);
	await spReceiptRowEvents.payerChanged(frm, first.doctype, first.name);
	assert.equal(calls.msgprint.length, 0);
	assert.ok(!calls.xcall.some((call) => call.method.endsWith("preview_receipt")));
	assert.deepEqual([first.receipt_recipient, first.receipt_currency], ["", "EUR"]);
	for (const source of moduleSources.filter((text) => !text.includes("spReceiptValidation = {"))) {
		assert.ok(!source.includes("msgprint"));
	}
	assert.ok(!formSource.includes("msgprint"));
});

function guardedGrid(frm) {
	const added = [];
	const grid = { frm, add_new_row: (...args) => added.push(args) };
	frm.fields_dict.operational_pairs = { grid };
	spReceiptValidation.installAddRowGuard(frm);
	return { grid, added };
}

test("11 Add Row with an incomplete last row is blocked with one message", async () => {
	reset();
	responses.preview_receipt = { ready: false, issues: [{ row: 1, field: "credit_amount", message: "مبلغ باید بزرگ‌تر از صفر باشد." }] };
	const frm = form({}, [row("row-1", { receipt_recipient_type: "Account", credit_account: "Cash - SP" })]);
	const { grid, added } = guardedGrid(frm);
	grid.add_new_row(null, null, true);
	await flush();
	assert.equal(added.length, 0);
	assert.equal(calls.msgprint.length, 1);
	assert.ok(calls.msgprint[0].message.includes("ردیف 1"));
});

test("12 Add Row with a complete or placeholder last row adds the row", async () => {
	reset();
	responses.preview_receipt = { ready: true, issues: [], rows: [{ row: 1, currency: "IRR", amount: "5", rate: "1", base_amount: "5" }] };
	const frm = form({}, [row("row-1", { receipt_recipient_type: "Account", credit_account: "Cash - SP", credit_amount: 5 })]);
	const { grid, added } = guardedGrid(frm);
	grid.add_new_row(null, null, true);
	await flush();
	assert.equal(added.length, 1);
	assert.equal(calls.msgprint.length, 0);
	reset();
	const placeholder = form({}, [row("row-2", { receipt_recipient_type: "Customer" })]);
	const second = guardedGrid(placeholder);
	second.grid.add_new_row();
	assert.equal(second.added.length, 1);
	assert.equal(calls.xcall.length, 0);
});

test("13 Save with an incomplete Receipt is blocked; a complete one passes", async () => {
	reset();
	responses.preview_receipt = { ready: false, issues: [{ row: null, field: "receipt_payer_account", message: "معین دریافت‌کننده الزامی است." }] };
	const frm = form({}, [row("row-3", { credit_amount: 5 }), row("row-4", { receipt_recipient_type: "Customer" })]);
	await spReceiptValidation.validateSave(frm);
	assert.equal(frappe.validated, false);
	assert.equal(calls.msgprint.length, 1);
	assert.deepEqual(frm.doc.operational_pairs.map((candidate) => candidate.name), ["row-3"]);
	reset();
	responses.preview_receipt = { ready: true, issues: [], rows: [] };
	await spReceiptValidation.validateSave(form({}, [row("row-5", { credit_amount: 5 })]));
	assert.equal(frappe.validated, true);
	assert.equal(calls.msgprint.length, 0);
	assert.ok(!clientSource.includes("frappe.client.set_value"));
});

test("14 multi-currency summary and Base Amount come from the server preview", async () => {
	reset();
	responses.preview_receipt = {
		ready: true, issues: [], company_currency: "IRR",
		receiver_currency: "USD", receiver_rate: "1600000", receiver_amount: "1000",
		receiver_base_amount: "1600000000", receiver_effective_rate: "1600000", receiver_account: "Bank USD - SP",
		total_base_amount: "1600000000",
		payer_totals: [
			{ currency: "IRR", amount: "100000000", rate: "1", base_amount: "100000000" },
			{ currency: "EUR", amount: "750", rate: "2000000", base_amount: "1500000000" },
		],
		rows: [{ row: 1, currency: "IRR", amount: "100000000", rate: "1", base_amount: "1234" }],
	};
	const first = row("row-6", { credit_amount: 1000, credit_company_amount: 0 });
	const frm = form({ receipt_payer_currency: "USD" }, [first]);
	const preview = await spReceiptSummary.refreshNow(frm);
	assert.equal(spReceiptForm.state(frm).preview, preview);
	assert.equal(first.credit_company_amount, 1234);
	const html = spReceiptSummary.html(preview, frm.doc, (value) => `#${value}`, (value) => value);
	assert.equal((html.match(/sp-receipt-payer-values/g) || []).length, 2);
	for (const text of [
		"<td>EUR</td><td>#750</td><td>#2000000</td><td>#1500000000 IRR</td>",
		"<td>IRR</td><td>#100000000</td><td>#1</td><td>#100000000 IRR</td>",
		"<td>USD</td><td>#1000</td><td>#1600000</td><td>#1600000000 IRR</td>",
		"Bank USD - SP", "colspan=\"4\"", "میانگین موزون نرخ", "ارز دریافت‌کننده",
	]) {
		assert.ok(html.includes(text), text);
	}
	assert.equal((html.match(/<table/g) || []).length, 1);
});

test("15 no authoritative JS money state", async () => {
	reset();
	responses.preview_receipt = { ready: false, issues: [], rows: [] };
	const first = row("row-7", { credit_amount: 10, credit_company_amount: 15 });
	await spReceiptSummary.refreshNow(form({ receipt_payer_currency: "USD", receipt_payer_exchange_rate: 1.5 }, [first]));
	assert.equal(first.credit_company_amount, null);
	const receiptCode = moduleSources.join("\n");
	for (const pattern of [/amount\s*\*/, /\*\s*rate/, /\/\s*receiverRate/, /summarizeReceiptRows/, /weightedRate/]) {
		assert.ok(!pattern.test(receiptCode), String(pattern));
	}
});

test("16 the old staged validation mechanism is gone", () => {
	for (const text of ["advanceRowStage", "__sp_row_stage", "receiptRowStage", "smartprocess_receipt_stage", "message_log", "get_receipt_receiver_total", "headerReadinessIssue", "setRowValueQuietly", "locals["]) {
		assert.ok(!clientSource.includes(text), text);
	}
	assert.ok(!read(path.join(APP_DIR, "hooks.py")).includes("smartprocess_receipt_stage"));
	assert.ok(!fs.existsSync(path.join(APP_DIR, "public", "js", "smartprocess_receipt_stage.js")));
});

test("modules stay small and are included by the form", () => {
	for (const file of Object.values(MODULES)) {
		const lines = read(path.join(RECEIPT_DIR, file)).split("\n").length;
		assert.ok(lines <= 300, `${file}: ${lines} lines`);
		assert.ok(formSource.includes(`receipt/${file}" %}`), file);
	}
	assert.ok(formSource.split("\n").length <= 300);
});

(async () => {
	for (const [name, run] of tests) {
		await run();
		console.log(`ok - ${name}`);
	}
	reset();
	console.log(`receipt_ui: ${tests.length} tests passed`);
})().catch((error) => {
	console.error(error);
	process.exitCode = 1;
});
