// Pure Receipt UI tests: Frappe is stubbed, nothing touches a site.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const DOCTYPE_DIR = path.join(__dirname, "..", "doctype", "smartprocess_accounting_document");
const RECEIPT_DIR = path.join(DOCTYPE_DIR, "receipt");
const APP_DIR = path.join(__dirname, "..", "..");
const MODULES = {
	spReceiptConfig: "receipt_config.js",
	spFlowText: "flow_text.js",
	spReceiptNumbers: "receipt_numbers.js",
	spReceiptForm: "receipt_form.js",
	spReceiptHeader: "receipt_header.js",
	spReceiptPayerHeader: "receipt_payer_header.js",
	spReceiptRowQueries: "receipt_row_queries.js",
	spReceiptRowEvents: "receipt_row_events.js",
	spReceiptValidation: "receipt_validation_ui.js",
	spReceiptSummary: "receipt_summary.js",
	spReceiptConversionStatus: "receipt_conversion_status.js",
};

const calls = { xcall: [], msgprint: [], setValue: [], confirm: [] };
let responses = {};
let confirmAnswer = true;
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
	confirm(message, yes, no) {
		calls.confirm.push(message);
		(confirmAnswer ? yes : no)();
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
		receipt_credit_currency: "IRR",
		posting_date: "2026-10-05",
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
	calls.confirm = [];
	responses = {};
	confirmAnswer = true;
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
const gridProperty = (fieldname, property, doc = {}) =>
	spReceiptForm.receiptGridProperties(doc).filter(([field, prop]) => field === fieldname && prop === property).pop()?.[2];
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

test("4 row Party query uses the header Payer Currency, not the Receiver currency", () => {
	const doc = { operation_type: "Receipt", company: "SP", receipt_payer_currency: "EUR", receipt_credit_currency: "USD" };
	assert.deepEqual(spReceiptRowQueries.payerQuery(doc, { receipt_recipient_type: "Supplier", receipt_currency: "IRR" }).filters, {
		party_type: "Supplier", company: "SP", currency: "USD",
	});
	assert.deepEqual(spReceiptRowQueries.payerQuery(doc, { receipt_recipient_type: "Bank Account" }).filters, {
		company: "SP", currency: "USD",
	});
});

test("5 row Account query uses the header Payer Currency", () => {
	const doc = { company: "SP", receipt_payer_currency: "EUR", receipt_credit_currency: "USD" };
	const filters = (type) => spReceiptRowQueries.payerAccountFilters(doc, { receipt_recipient_type: type, receipt_currency: "IRR" });
	assert.equal(filters("Customer").account_currency, "USD");
	assert.equal(spReceiptRowQueries.payerAccountFilters({ company: "SP" }, { receipt_recipient_type: "Customer" }).account_currency, "");
	assert.equal(filters("Customer").account_type, "Receivable");
	assert.equal(filters("Employee").account_type, "Payable");
	assert.equal(filters("Bank Account").account_type, "Bank");
	assert.deepEqual(filters("Account").account_type, ["not in", ["Receivable", "Payable"]]);
	assert.deepEqual([filters("Account").disabled, filters("Account").is_group], [0, 0]);
});

test("6 one header Payer Currency; the row Currency is a read-only mirror outside the grid", async () => {
	reset();
	const header = docField("receipt_credit_currency");
	assert.deepEqual([header.fieldtype, header.label], ["Select", "ارز پرداخت‌کننده"]);
	assert.equal(docMeta.field_order.indexOf("receipt_credit_currency"), docMeta.field_order.indexOf("company_currency") + 1);
	assert.equal(Boolean(evalDepends(docField("company_currency").depends_on, { operation_type: "Receipt" })), false);
	const currency = pairField("receipt_currency");
	assert.deepEqual([currency.hidden, currency.read_only, currency.in_list_view], [undefined, 1, undefined]);
	assert.deepEqual(
		["hidden", "read_only", "in_list_view", "reqd"].map((property) => gridProperty("receipt_currency", property)),
		[0, 1, 0, undefined],
	);
	assert.ok(!/receipt_currency\(frm, cdt, cdn\)/.test(formSource));
	assert.ok(/receipt_credit_currency\(frm\)/.test(formSource));
	const fresh = row("row-c1", {});
	const kept = row("row-c2", { receipt_currency: "EUR", credit_amount: 5, credit_exchange_rate: 900000 });
	const frm = form({ receipt_payer_currency: "USD", receipt_credit_currency: "IRR" }, [fresh, kept]);
	await spReceiptRowEvents.applyDefaults(frm, fresh);
	await spReceiptRowEvents.applyDefaults(frm, kept);
	assert.deepEqual([fresh.receipt_currency, fresh.credit_exchange_rate], ["IRR", 1]);
	assert.equal(kept.receipt_currency, "EUR");
});

test("7 row rate: base Payer Currency is 1 and hidden from the grid; foreign rates differ per row", async () => {
	reset();
	assert.equal(gridProperty("credit_exchange_rate", "hidden"), 0);
	const readOnly = gridProperty("credit_exchange_rate", "read_only_depends_on");
	assert.equal(Boolean(evalDepends(readOnly, {}, { company_currency: "IRR", receipt_credit_currency: "IRR" })), true);
	assert.equal(Boolean(evalDepends(readOnly, {}, { company_currency: "IRR", receipt_credit_currency: "USD" })), false);
	const base = { company_currency: "IRR", receipt_credit_currency: "IRR" };
	assert.equal(gridProperty("credit_exchange_rate", "in_list_view", base), 0);
	assert.equal(gridProperty("credit_exchange_rate", "in_list_view", { ...base, receipt_credit_currency: "USD" }), 1);
	assert.equal(gridProperty("credit_company_amount", "read_only"), 1);
	const first = row("row-r1", { credit_exchange_rate: 1600000 });
	const second = row("row-r2", { credit_exchange_rate: 1550000 });
	const foreignForm = form({ receipt_credit_currency: "USD" }, [first, second]);
	await spReceiptRowEvents.rateChanged(foreignForm, first.doctype, first.name);
	await spReceiptRowEvents.rateChanged(foreignForm, second.doctype, second.name);
	assert.deepEqual([first.credit_exchange_rate, second.credit_exchange_rate], [1600000, 1550000]);
	const baseRow = row("row-r3", { credit_exchange_rate: 5 });
	await spReceiptRowEvents.rateChanged(form({}, [baseRow]), baseRow.doctype, baseRow.name);
	assert.equal(baseRow.credit_exchange_rate, 1);
	const payload = spReceiptSummary.payload({ receipt_credit_currency: "USD", operational_pairs: [first] });
	assert.deepEqual([payload.receipt_credit_currency, payload.operational_pairs[0].credit_exchange_rate], ["USD", 1600000]);
});

test("7b Payer Currency change asks first, then clears only rows filled in the old currency", async () => {
	reset();
	const filled = () => row("row-x1", {
		receipt_currency: "USD", credit_exchange_rate: 1600000, receipt_recipient_type: "Customer",
		receipt_recipient: "C1", credit_account: "Debtors USD", credit_amount: 2, receipt_posting_date: "2026-10-01",
	});
	let first = filled();
	const placeholder = row("row-x2", { receipt_currency: "USD", receipt_recipient_type: "Customer" });
	let frm = form({ receipt_credit_currency: "EUR" }, [first, placeholder]);
	spReceiptForm.state(frm).payerCurrency = "USD";
	confirmAnswer = false;
	await spReceiptPayerHeader.currencyChanged(frm);
	assert.equal(calls.confirm.length, 1);
	assert.ok(calls.confirm[0].includes("USD") && calls.confirm[0].includes("EUR") && calls.confirm[0].includes("1 ردیف"));
	assert.equal(frm.doc.receipt_credit_currency, "USD");
	assert.deepEqual([first.receipt_currency, first.receipt_recipient, first.credit_account, first.credit_exchange_rate], ["USD", "C1", "Debtors USD", 1600000]);

	reset();
	first = filled();
	frm = form({ receipt_credit_currency: "EUR" }, [first, placeholder]);
	spReceiptForm.state(frm).payerCurrency = "USD";
	await spReceiptPayerHeader.currencyChanged(frm);
	assert.equal(calls.confirm.length, 1);
	assert.deepEqual([first.receipt_currency, first.receipt_recipient, first.credit_account, first.credit_exchange_rate], ["EUR", "", "", null]);
	assert.deepEqual([first.receipt_recipient_type, first.credit_amount, first.receipt_posting_date], ["Customer", 2, "2026-10-01"]);
	assert.equal(placeholder.receipt_currency, "EUR");

	reset();
	frm.doc.receipt_credit_currency = "IRR";
	await spReceiptPayerHeader.currencyChanged(frm);
	assert.equal(calls.confirm.length, 0);
	assert.deepEqual([first.receipt_currency, first.credit_exchange_rate], ["IRR", 1]);
	assert.equal(calls.msgprint.length, 0);
});

test("7c Add Row inherits the Payer Currency and the document date, and copies the rate", async () => {
	reset();
	responses.get_receipt_recipient_type_default = "Customer";
	responses.get_receipt_recipient_type_options = [];
	const first = row("row-a1", { receipt_currency: "USD", credit_exchange_rate: 1600000, receipt_recipient_type: "Customer", receipt_posting_date: "2026-09-01" });
	const second = row("row-a2", {});
	const frm = form({ receipt_credit_currency: "USD", posting_date: "2026-10-05" }, [first, second]);
	await spReceiptRowEvents.rowAdded(frm, second.doctype, second.name);
	assert.deepEqual([second.receipt_currency, second.credit_exchange_rate, second.receipt_posting_date], ["USD", 1600000, "2026-10-05"]);
});

test("7e document date: existing row dates stay, one warning, new rows take the new date", async () => {
	reset();
	responses.get_receipt_recipient_type_default = "Customer";
	responses.get_receipt_recipient_type_options = [];
	const dated = [1, 2, 3].map((index) => row(`row-d${index}`, { receipt_posting_date: "2026-10-05", credit_amount: index }));
	const untouched = row("row-d4", { receipt_posting_date: "2026-10-05", receipt_recipient_type: "Customer" });
	const frm = form({ posting_date: "2026-10-05" }, [...dated, untouched]);
	frm.doc.posting_date = "2026-10-07";
	await spReceiptPayerHeader.postingDateChanged(frm);
	assert.deepEqual(dated.map((candidate) => candidate.receipt_posting_date), Array(3).fill("2026-10-05"));
	assert.equal(untouched.receipt_posting_date, "2026-10-07");
	assert.equal(calls.msgprint.length, 1);
	assert.ok(calls.msgprint[0].message.includes("همگام نمی‌شود"));
	const added = row("row-d5", {});
	frm.doc.operational_pairs.push(added);
	await spReceiptRowEvents.rowAdded(frm, added.doctype, added.name);
	assert.equal(added.receipt_posting_date, "2026-10-07");
	reset();
	const fresh = form({ posting_date: "2026-10-05" }, [row("row-d6", { receipt_recipient_type: "Customer" })]);
	fresh.doc.posting_date = "2026-10-08";
	await spReceiptPayerHeader.postingDateChanged(fresh);
	assert.equal(calls.msgprint.length, 0);
});

test("7f Payer Currency defaults from Company or from the rows of an older Receipt", async () => {
	reset();
	const blank = form({ receipt_credit_currency: "", company_currency: "EUR" });
	await spReceiptPayerHeader.applyDefault(blank, false);
	assert.equal(blank.doc.receipt_credit_currency, "EUR");
	const legacy = form({ receipt_credit_currency: "" }, [row("row-l1", { receipt_currency: "USD", credit_amount: 1 })]);
	await spReceiptPayerHeader.applyDefault(legacy, false);
	assert.equal(legacy.doc.receipt_credit_currency, "USD");
	const filled = form({ receipt_credit_currency: "USD" }, [row("row-l2", { receipt_currency: "USD", credit_amount: 1 })]);
	await spReceiptPayerHeader.applyDefault(filled, true);
	assert.equal(filled.doc.receipt_credit_currency, "USD");
	assert.equal(calls.confirm.length, 0);
});

test("7d Receiver currency change keeps every row currency and payer", async () => {
	reset();
	const first = row("row-h1", { receipt_currency: "USD", credit_exchange_rate: 1600000, receipt_recipient: "C1", credit_account: "Debtors USD" });
	const frm = form({ receipt_payer_currency: "EUR", receipt_credit_currency: "USD", receipt_payer_account: "Bank IRR" }, [first]);
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
	const frm = form({ receipt_payer_currency: "USD", receipt_credit_currency: "EUR", receipt_bank_account: "B" }, [first]);
	spReceiptForm.state(frm).currency = "IRR";
	spReceiptForm.state(frm).payerCurrency = "";
	await spReceiptHeader.currencyChanged(frm);
	await spReceiptHeader.receiverKindChanged(frm);
	await spReceiptHeader.bankChanged(frm);
	await spReceiptHeader.partyChanged(frm);
	await spReceiptHeader.rateChanged(frm);
	await spReceiptPayerHeader.currencyChanged(frm);
	await spReceiptPayerHeader.postingDateChanged(frm);
	await spReceiptRowEvents.rateChanged(frm, first.doctype, first.name);
	await spReceiptRowEvents.payerTypeChanged(frm, first.doctype, first.name);
	await spReceiptRowEvents.payerChanged(frm, first.doctype, first.name);
	assert.equal(calls.msgprint.length, 0);
	assert.equal(calls.confirm.length, 0);
	assert.ok(!calls.xcall.some((call) => call.method.endsWith("preview_receipt")));
	assert.deepEqual([first.receipt_recipient, first.receipt_currency], ["", "EUR"]);
	const payerHeader = read(path.join(RECEIPT_DIR, MODULES.spReceiptPayerHeader));
	assert.equal(payerHeader.split("msgprint").length - 1, 1);
	assert.ok(/warnRowDates\(\) \{\s+frappe\.msgprint\(/.test(payerHeader));
	for (const source of moduleSources.filter((text) => !text.includes("spReceiptValidation = {") && text !== payerHeader)) {
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

test("14 Payer Currency summary and Base Amount come from the server preview", async () => {
	reset();
	responses.preview_receipt = {
		ready: true, issues: [], company_currency: "IRR", payer_currency: "EUR",
		receiver_currency: "USD", receiver_rate: "1600000", receiver_amount: "937.5",
		receiver_base_amount: "1500000000", receiver_effective_rate: "1600000", receiver_account: "Bank USD - SP",
		total_base_amount: "1500000000",
		payer_totals: [{ currency: "EUR", amount: "750", rate: "2000000", base_amount: "1500000000" }],
		rows: [{ row: 1, currency: "EUR", amount: "750", rate: "2000000", base_amount: "1234" }],
	};
	const first = row("row-6", { credit_amount: 750, credit_company_amount: 0 });
	const frm = form({ receipt_payer_currency: "USD", receipt_credit_currency: "EUR" }, [first]);
	const preview = await spReceiptSummary.refreshNow(frm);
	assert.equal(spReceiptForm.state(frm).preview, preview);
	assert.equal(first.credit_company_amount, 1234);
	const html = spReceiptSummary.html(preview, frm.doc, (value) => `#${value}`, (value) => value);
	assert.equal((html.match(/sp-receipt-payer-values/g) || []).length, 1);
	for (const text of [
		"<td>EUR</td><td>#750</td><td>#2000000</td><td>#1500000000 IRR</td>",
		"<td>USD</td><td>#937.5</td><td>#1600000</td><td>#1500000000 IRR</td>",
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

test("17 read-only Base Amount cell drops trailing zeros only when the global setting is on", () => {
	require(path.join(APP_DIR, "public", "js", "smartprocess_numeric.js"));
	globalThis.get_number_format = () => "#,###.##";
	globalThis.get_number_format_info = () => ({ decimal_str: ".", group_sep: "," });
	const frm = form({}, [row("base-1", { credit_company_amount: 15000 })]);
	const control = (doc) => ({
		df: { fieldtype: "Currency", fieldname: "credit_company_amount", read_only: 1, precision: "9" },
		doc,
		value: doc.credit_company_amount,
		format_for_input: (value) => (value === 15000 ? "15,000.000000000" : String(value)),
	});
	const doc = docs.get("base-1");
	try {
		frappe.boot = { smartprocess_accounting: { hide_insignificant_trailing_zeros: 1 } };
		const on = control(doc);
		spReceiptNumbers.prepare(frm, on);
		assert.equal(on.format_for_input(15000), "15,000");
		frappe.boot = { smartprocess_accounting: { hide_insignificant_trailing_zeros: 0 } };
		const off = control(doc);
		spReceiptNumbers.prepare(frm, off);
		assert.equal(off.format_for_input(15000), "15,000.000000000");
		assert.equal(doc.credit_company_amount, 15000, "the stored Base Amount stays the raw number");
	} finally {
		delete frappe.boot;
	}
});

test("18 Payment rows edit the debit side; the Receipt grid stays on the credit side", () => {
	const payment = { operation_type: "Payment", company_currency: "IRR", receipt_credit_currency: "IRR" };
	assert.deepEqual(
		["debit_account", "debit_amount", "debit_company_amount"].map((field) => gridProperty(field, "in_list_view", payment)),
		[1, 1, 1],
	);
	assert.deepEqual([gridProperty("debit_account", "reqd", payment), gridProperty("debit_amount", "reqd", payment)], [1, 1]);
	assert.deepEqual([gridProperty("credit_amount", "hidden", payment), gridProperty("credit_amount", "reqd", payment)], [1, 0]);
	assert.equal(gridProperty("debit_exchange_rate", "in_list_view", payment), 0);
	assert.equal(gridProperty("debit_exchange_rate", "in_list_view", { ...payment, receipt_credit_currency: "USD" }), 1);
	assert.deepEqual(
		["receipt_recipient_type", "receipt_recipient", "debit_account"].map((field) => gridProperty(field, "label", payment)),
		["نوع دریافت‌کننده", "دریافت‌کننده", "معین دریافت‌کننده"],
	);
	assert.deepEqual([gridProperty("credit_amount", "in_list_view"), gridProperty("debit_amount", "hidden")], [1, 1]);
	assert.equal(gridProperty("receipt_recipient", "label"), "پرداخت‌کننده");
	const restored = spReceiptForm.genericGridProperties().map(([field, property]) => `${field}:${property}`);
	assert.ok(restored.includes("debit_account:label") && restored.includes("credit_account:label"));
});

test("19 Payment header labels mirror Receipt; Receipt keeps its DocType labels", () => {
	const base = (field) => docField(field)?.label;
	const payment = spFlowText.headerLabels({ operation_type: "Payment" }, base);
	assert.deepEqual(
		[payment.receipt_receiver_kind, payment.receipt_payer_currency, payment.receipt_credit_currency],
		["نوع پرداخت‌کننده", "ارز پرداخت‌کننده", "ارز دریافت‌کننده"],
	);
	const receipt = spFlowText.headerLabels({ operation_type: "Receipt" }, base);
	for (const [field, label] of Object.entries(receipt)) {
		assert.equal(label, base(field), field);
	}
	assert.equal(receipt.receipt_credit_currency, "ارز پرداخت‌کننده");
});

test("20 Payment preview, payload, Base Amount and placeholder checks use the debit side", async () => {
	reset();
	responses.preview_payment = { ready: true, issues: [], rows: [{ row: 1, currency: "USD", amount: "2", rate: "1600000", base_amount: "3200000" }] };
	const first = row("pay-1", { debit_account: "Creditors USD", debit_amount: 2, debit_exchange_rate: 1600000, credit_amount: 99 });
	const frm = form({ operation_type: "Payment", receipt_credit_currency: "USD" }, [first]);
	await spReceiptSummary.refreshNow(frm);
	assert.deepEqual(calls.xcall.map((call) => call.method.split(".").slice(-2).join(".")), ["payment_api.preview_payment"]);
	const sent = calls.xcall[0].args.doc.operational_pairs[0];
	assert.deepEqual([sent.debit_account, sent.debit_amount, sent.debit_exchange_rate, "credit_amount" in sent], ["Creditors USD", 2, 1600000, false]);
	assert.equal(first.debit_company_amount, 3200000);
	const placeholder = { receipt_recipient_type: "Supplier", credit_amount: 5 };
	assert.equal(spReceiptValidation.rowHasUserContent(placeholder, frm.doc), false);
	assert.equal(spReceiptValidation.rowHasUserContent({ debit_amount: 5 }, frm.doc), true);
	assert.equal(spReceiptValidation.rowHasUserContent(placeholder, { operation_type: "Receipt" }), true);
	const html = spReceiptSummary.html({ receiver_currency: "IRR" }, frm.doc, String, String);
	assert.ok(html.includes("مجموع برداشت از پرداخت‌کننده") && html.includes("ارز پرداخت‌کننده"));
});

test("21 Payment row events copy and clear the debit side", async () => {
	reset();
	responses.get_receipt_recipient_type_default = "Supplier";
	responses.get_receipt_recipient_type_options = [];
	const first = row("pay-a1", { receipt_currency: "USD", debit_exchange_rate: 1600000, receipt_recipient_type: "Supplier" });
	const second = row("pay-a2", {});
	const frm = form({ operation_type: "Payment", receipt_credit_currency: "USD" }, [first, second]);
	await spReceiptRowEvents.rowAdded(frm, second.doctype, second.name);
	assert.deepEqual([second.debit_exchange_rate, second.credit_exchange_rate], [1600000, undefined]);
	const base = row("pay-a3", { debit_exchange_rate: 5 });
	await spReceiptRowEvents.rateChanged(form({ operation_type: "Payment" }, [base]), base.doctype, base.name);
	assert.equal(base.debit_exchange_rate, 1);
});

test("22 a Payment submitted before Payment V1 keeps the generic two-sided grid", () => {
	const legacy = { operation_type: "Payment", docstatus: 1, receipt_payer_account: "" };
	assert.equal(spReceiptConfig.isFlow(legacy), false);
	assert.equal(spReceiptConfig.isFlow({ ...legacy, docstatus: 2 }), false);
	assert.equal(spReceiptConfig.isFlow({ ...legacy, receipt_payer_account: "Bank - SP" }), true);
	assert.equal(spReceiptConfig.isFlow({ ...legacy, docstatus: 0 }), true);
	assert.equal(spReceiptConfig.isFlow({ operation_type: "Receipt", docstatus: 1 }), true);
});

test("23 a same-currency row starts from the header rate and keeps a typed rate", async () => {
	reset();
	const empty = row("same-1", {});
	const typed = row("same-2", { credit_exchange_rate: 1300 });
	const values = { receipt_payer_currency: "USD", receipt_credit_currency: "USD", receipt_payer_exchange_rate: 1200 };
	const frm = form(values, [empty, typed]);
	await spReceiptRowEvents.normalizeRate(frm, empty, false);
	await spReceiptRowEvents.normalizeRate(frm, typed, false);
	assert.deepEqual([empty.credit_exchange_rate, typed.credit_exchange_rate], [1200, 1300]);
	const cross = row("cross-1", {});
	await spReceiptRowEvents.normalizeRate(form({ ...values, receipt_payer_currency: "IRR" }, [cross]), cross, false);
	assert.equal(cross.credit_exchange_rate, undefined);
	const payment = row("same-p", {});
	await spReceiptRowEvents.normalizeRate(form({ ...values, operation_type: "Payment" }, [payment]), payment, false);
	assert.equal(payment.debit_exchange_rate, 1200);
});

test("24 section and grid titles follow the flow without touching layout metadata", () => {
	const titled = (values) => {
		const frm = form(values);
		const indicator = { nodeType: 1, textContent: "" };
		const text = { nodeType: 3, textContent: "\n Operational Pairs\n" };
		const grid = { length: 1, value: "Operational Pairs", text(value) { this.value = value; } };
		const properties = [];
		frm.fields_dict.pairs_section = { head: { get: () => ({ childNodes: [text, indicator] }) } };
		frm.fields_dict.operational_pairs = { $wrapper: { find: () => ({ first: () => grid }) } };
		frm.set_df_property = (fieldname, property) => properties.push(property);
		spReceiptHeader.configure(frm, spReceiptConfig.isFlow(frm.doc));
		return { section: text.textContent.trim(), grid: grid.value, indicator, properties };
	};
	const receipt = titled({});
	assert.deepEqual([receipt.section, receipt.grid], ["پرداخت‌کنندگان", "ردیف‌های رسید"]);
	assert.equal(receipt.indicator.nodeType, 1);
	const payment = titled({ operation_type: "Payment" });
	assert.deepEqual([payment.section, payment.grid], ["دریافت‌کنندگان", "ردیف‌های پرداخت"]);
	const generic = titled({ operation_type: "Journal" });
	assert.deepEqual([generic.section, generic.grid], ["Operational Pairs", "Operational Pairs"]);
	const touched = new Set([...receipt.properties, ...payment.properties, ...generic.properties]);
	assert.deepEqual([...touched].filter((property) => !["label", "formatter", "options"].includes(property)), []);
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
