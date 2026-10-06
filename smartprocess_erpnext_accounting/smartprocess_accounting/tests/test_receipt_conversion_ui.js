// Pure Receipt Conversion UI tests: Frappe is stubbed, nothing touches a site.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const DOCTYPE_DIR = path.join(__dirname, "..", "doctype");
const CONVERSION_DIR = path.join(DOCTYPE_DIR, "smartprocess_receipt_conversion");
const LEG = "SmartProcess Receipt Conversion Leg";

const calls = { xcall: [], confirm: [], setValue: [], alerts: [] };
let responses = {};
let confirmAnswer = true;
const docs = new Map();
const linkTitles = {};

globalThis.window = globalThis;
globalThis.frappe = {
	xcall(method, args) {
		calls.xcall.push({ method, args });
		const response = responses[method.split(".").pop()];
		return Promise.resolve(typeof response === "function" ? response(args) : response);
	},
	confirm(message, yes, no) {
		calls.confirm.push(message);
		(confirmAnswer ? yes : no)();
	},
	throw(message) {
		throw new Error(message);
	},
	show_alert(options) {
		calls.alerts.push(options);
	},
	get_doc(doctype, name) {
		return docs.get(name);
	},
	model: {
		async set_value(doctype, name, fieldname, value) {
			calls.setValue.push({ name, fieldname, value });
			docs.get(name)[fieldname] = value;
		},
	},
	meta: { docfield_map: {}, get_docfield: () => null },
	listview_settings: {},
	utils: {
		escape_html: (value) => String(value).replace(/</g, "&lt;"),
		add_link_title: (doctype, name, title) => (linkTitles[`${doctype}::${name}`] = title),
		get_link_title: (doctype, name) => linkTitles[`${doctype}::${name}`],
	},
};
const RECEIPT_DIR = path.join(DOCTYPE_DIR, "smartprocess_accounting_document", "receipt");
globalThis.spReceiptConfig = require(path.join(RECEIPT_DIR, "receipt_config.js"));
globalThis.spReceiptConversionStatus = require(path.join(RECEIPT_DIR, "receipt_conversion_status.js"));
globalThis.spConversionLegs = require(path.join(CONVERSION_DIR, "conversion", "conversion_legs.js"));
globalThis.spConversionSides = require(path.join(CONVERSION_DIR, "conversion", "conversion_sides.js"));
globalThis.spConversionForm = require(path.join(CONVERSION_DIR, "conversion", "conversion_form.js"));
globalThis.spReceiptNumbers = require(path.join(RECEIPT_DIR, "receipt_numbers.js"));
globalThis.spBalanceForm = require(path.join(CONVERSION_DIR, "conversion", "balance_form.js"));
spConversionForm.PREVIEW_DELAY = 0;
spBalanceForm.DELAY = 0;

function serverLeg(side, values = {}) {
	return {
		source_pair: "pair-1",
		source_side: side,
		source_posting: "SP-POST-1",
		source_account: side === "Receiver" ? "Bank - SP" : "Debtors - SP",
		source_party_type: side === "Receiver" ? null : "Customer",
		source_party: side === "Receiver" ? null : "CUST-1",
		company_currency: "IRR",
		original_amount: "100000000",
		already_converted: "0",
		remaining_amount: "100000000",
		conversion_amount: 0,
		target_currency: "USD",
		...values,
	};
}

function form(values = {}) {
	let counter = 0;
	const doc = {
		doctype: "SmartProcess Receipt Conversion",
		name: "new-conversion",
		docstatus: 0,
		source_receipt: "SP-REC-1",
		company: "SP",
		target_currency: "",
		legs: [],
		...values,
	};
	const frm = {
		doc,
		docname: doc.name,
		fields_dict: {},
		refreshed: 0,
		tableProperties: {},
		set_query() {},
		set_df_property(fieldname, property, value) {
			this.tableProperties[`${fieldname}:${property}`] = value;
		},
		refresh_field() {
			this.refreshed++;
		},
		clear_table(fieldname) {
			doc[fieldname] = [];
		},
		add_child(fieldname, row) {
			const child = { doctype: LEG, name: `leg-${++counter}`, parent: doc.name, ...row };
			docs.set(child.name, child);
			doc[fieldname].push(child);
			return child;
		},
		async set_value(fieldname, value) {
			doc[fieldname] = value;
			await spConversionForm.currencyChanged(frm);
		},
	};
	spConversionForm.state(frm);
	return frm;
}

async function selectCurrency(frm, currency) {
	frm.doc.target_currency = currency;
	await spConversionForm.currencyChanged(frm);
	await settle();
}

function reset() {
	calls.xcall = [];
	calls.confirm = [];
	calls.setValue = [];
	calls.alerts = [];
	confirmAnswer = true;
	responses = {
		get_conversion_legs: () => ({
			legs: [serverLeg("Receiver"), serverLeg("Payer", { target_party_type: "Customer" })],
			titles: { Customer: { "CUST-1": "مشتری یک" } },
		}),
		preview_target_amounts: ({ legs }) =>
			Object.fromEntries(legs.map((leg) => [leg.name, Number(leg.conversion_amount) && Number(leg.target_rate) ? "1111.11" : "0"])),
	};
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 5));
const tests = [];
const test = (name, run) => tests.push([name, run]);
const read = (file) => fs.readFileSync(file, "utf-8");
const legMeta = JSON.parse(read(path.join(DOCTYPE_DIR, "smartprocess_receipt_conversion_leg", "smartprocess_receipt_conversion_leg.json")));
const conversionMeta = JSON.parse(read(path.join(CONVERSION_DIR, "smartprocess_receipt_conversion.json")));
const field = (meta, fieldname) => meta.fields.find((df) => df.fieldname === fieldname);

test("selecting the first currency loads every server leg without a confirmation", async () => {
	const frm = form();
	await selectCurrency(frm, "USD");
	assert.equal(calls.confirm.length, 0);
	assert.deepEqual(frm.doc.legs.map((leg) => leg.source_side), ["Receiver", "Payer"]);
	assert.deepEqual(calls.xcall[0].args, { source_receipt: "SP-REC-1", target_currency: "USD" });
	assert.equal(frm.doc.legs[1].target_party_type, "Customer");
});

test("a new Conversion drops Frappe's default Company currency and empty mandatory row", async () => {
	const frm = form({ __islocal: 1, target_currency: "IRR", legs: [{ doctype: LEG, name: "empty-row" }] });
	responses.get_company_currency = "IRR";
	await spConversionForm.refresh(frm);
	assert.equal(frm.doc.target_currency, "");
	assert.deepEqual(frm.doc.legs, []);
	assert.deepEqual(frm.tableProperties, { "legs:cannot_add_rows": 1, "legs:cannot_delete_rows": 1 });
	assert.ok(!calls.xcall.some((call) => call.method.endsWith("get_conversion_legs")));
	await selectCurrency(frm, "USD");
	assert.equal(calls.confirm.length, 0);
	assert.equal(frm.doc.legs.length, 2);
});

test("only server legs are shown: a foreign side the server does not return never appears", async () => {
	const frm = form();
	responses.get_conversion_legs = { legs: [serverLeg("Receiver")], titles: {} };
	await selectCurrency(frm, "USD");
	assert.deepEqual(frm.doc.legs.map((leg) => leg.source_side), ["Receiver"]);
});

test("a prefilled suggestion alone never asks for a confirmation", async () => {
	const frm = form();
	responses.get_conversion_legs = { legs: [serverLeg("Payer", { target_account: "USD Debtors - SP" })], titles: {} };
	await selectCurrency(frm, "USD");
	await selectCurrency(frm, "EUR");
	assert.equal(calls.confirm.length, 0);
});

test("a currency change after a rate asks once and resets targets but keeps amounts", async () => {
	const frm = form();
	await selectCurrency(frm, "USD");
	const [receiver, payer] = frm.doc.legs;
	Object.assign(receiver, { conversion_amount: 100000000, target_rate: 90000, target_account: "USD Bank - SP" });
	Object.assign(payer, { conversion_amount: 50000000, target_rate: 100000, target_party: "CUST-9" });
	await selectCurrency(frm, "EUR");
	assert.equal(calls.confirm.length, 1);
	const [newReceiver, newPayer] = frm.doc.legs;
	assert.deepEqual([newReceiver.conversion_amount, newPayer.conversion_amount], [100000000, 50000000]);
	for (const leg of frm.doc.legs) {
		assert.equal(leg.target_rate, undefined);
		assert.equal(leg.target_account, undefined);
		assert.equal(leg.target_currency, "EUR");
	}
	assert.equal(newPayer.target_party, undefined);
	assert.equal(newPayer.target_party_type, "Customer", "the new currency's suggestion is reloaded");
});

test("cancelling the confirmation restores the previous currency and keeps every row", async () => {
	const frm = form();
	await selectCurrency(frm, "USD");
	Object.assign(frm.doc.legs[0], { conversion_amount: 100000000, target_rate: 90000 });
	const before = frm.doc.legs;
	confirmAnswer = false;
	await selectCurrency(frm, "EUR");
	assert.equal(calls.confirm.length, 1);
	assert.equal(frm.doc.target_currency, "USD");
	assert.equal(frm.doc.legs, before);
	assert.equal(frm.doc.legs[0].target_rate, 90000);
	assert.equal(calls.xcall.filter((call) => call.method.endsWith("get_conversion_legs")).length, 1);
});

test("a user-edited target counts as input even before a rate", async () => {
	const frm = form();
	await selectCurrency(frm, "USD");
	spConversionForm.targetTouched(frm, LEG, frm.doc.legs[0].name);
	await selectCurrency(frm, "EUR");
	assert.equal(calls.confirm.length, 1);
});

test("preview writes only target_amount and never the business rate", async () => {
	const frm = form();
	await selectCurrency(frm, "USD");
	const [receiver, payer] = frm.doc.legs;
	Object.assign(receiver, { conversion_amount: 100000000, target_rate: 90000 });
	calls.setValue = [];
	spConversionForm.rateChanged(frm, LEG, receiver.name);
	await settle();
	assert.equal(receiver.target_amount, 1111.11);
	assert.equal(receiver.target_rate, 90000);
	assert.equal(payer.target_amount, 0, "a zero leg stays with a zero Target Amount");
	assert.ok(calls.setValue.every((call) => call.fieldname === "target_amount"));
});

test("receiver and payer are sent independently: 100m/0 and 100m/50m at different rates", async () => {
	const frm = form();
	await selectCurrency(frm, "USD");
	const [receiver, payer] = frm.doc.legs;
	Object.assign(receiver, { conversion_amount: 100000000, target_rate: 90000 });
	spConversionForm.amountChanged(frm);
	await settle();
	let sent = calls.xcall.filter((call) => call.method.endsWith("preview_target_amounts")).pop().args.legs;
	assert.deepEqual(sent.map((leg) => [leg.conversion_amount, leg.target_rate]), [[100000000, 90000], [0, undefined]]);
	Object.assign(payer, { conversion_amount: 50000000, target_rate: 100000 });
	spConversionForm.amountChanged(frm);
	await settle();
	sent = calls.xcall.filter((call) => call.method.endsWith("preview_target_amounts")).pop().args.legs;
	assert.deepEqual(sent.map((leg) => [leg.conversion_amount, leg.target_rate]), [[100000000, 90000], [50000000, 100000]]);
	assert.equal(frm.doc.legs.length, 2, "rows are never merged or removed");
});

test("a stale preview response is ignored", async () => {
	const frm = form();
	await selectCurrency(frm, "USD");
	const receiver = frm.doc.legs[0];
	let release;
	responses.preview_target_amounts = () => new Promise((resolve) => (release = () => resolve({ [receiver.name]: "1" })));
	const first = spConversionForm.preview(frm);
	responses.preview_target_amounts = { [receiver.name]: "2" };
	await spConversionForm.preview(frm);
	release();
	await first;
	assert.equal(receiver.target_amount, 2);
});

test("کل مانده copies the remaining amount and still allows manual amounts", async () => {
	const frm = form();
	await selectCurrency(frm, "USD");
	const payer = frm.doc.legs[1];
	payer.remaining_amount = "70000000";
	await spConversionForm.fillRemaining(frm, LEG, payer.name);
	assert.equal(payer.conversion_amount, "70000000");
	frm.doc.docstatus = 1;
	payer.remaining_amount = "1";
	await spConversionForm.fillRemaining(frm, LEG, payer.name);
	assert.equal(payer.conversion_amount, "70000000", "a submitted Conversion never changes");
});

test("submit with every amount zero stops with a Persian message", async () => {
	const frm = form();
	await selectCurrency(frm, "USD");
	assert.throws(() => spConversionForm.beforeSubmit(frm), /حداقل یک ردیف/);
	frm.doc.legs[0].conversion_amount = 1;
	spConversionForm.beforeSubmit(frm);
});

test("account and party filters follow the target currency and the chosen Party", () => {
	assert.deepEqual(spConversionLegs.accountFilters("SP", "USD", "Customer", ""), {
		company: "SP",
		disabled: 0,
		is_group: 0,
		account_currency: "USD",
	});
	assert.equal(spConversionLegs.accountFilters("SP", "USD", "Customer", "CUST-1").account_type, "Receivable");
	assert.equal(spConversionLegs.accountFilters("SP", "USD", "Supplier", "SUP-1").account_type, "Payable");
	assert.deepEqual(spConversionLegs.currencyFilters("IRR"), { enabled: 1, name: ["!=", "IRR"] });
});

test("grid labels: Persian side and party · account", async () => {
	const frm = form();
	await selectCurrency(frm, "USD");
	const formatters = spConversionForm.formatters();
	const payer = frm.doc.legs[1];
	assert.equal(formatters.source_side("Receiver"), "دریافت‌کننده");
	assert.equal(formatters.source_side("Payer"), "پرداخت‌کننده");
	assert.equal(formatters.source_account(payer.source_account, {}, {}, payer), "مشتری یک · Debtors - SP");
	assert.equal(formatters.source_account("Bank - SP", {}, {}, frm.doc.legs[0]), "Bank - SP");
	assert.equal(formatters.target_account("<x>", {}, {}, {}), "&lt;x>");
	const options = spConversionForm.gridProperties().find(([fieldname, property]) => fieldname === "source_side" && property === "options")[2];
	assert.deepEqual(options, [
		{ value: "Receiver", label: "دریافت‌کننده" },
		{ value: "Payer", label: "پرداخت‌کننده" },
	]);
});

test("leg grid columns are the agreed compact set, in order", () => {
	const columns = legMeta.field_order.filter((fieldname) => field(legMeta, fieldname).in_list_view);
	assert.deepEqual(columns, [
		"source_side",
		"source_account",
		"original_amount",
		"already_converted",
		"remaining_amount",
		"conversion_amount",
		"target_rate",
		"target_amount",
		"target_account",
		"fill_remaining",
	]);
	const width = columns.reduce((total, fieldname) => total + field(legMeta, fieldname).columns, 0);
	assert.ok(width > 10, "past 10 columns Frappe scrolls the grid instead of truncating headers");
	for (const fieldname of ["source_side", "source_account", "original_amount", "already_converted", "remaining_amount", "target_amount"]) {
		assert.equal(field(legMeta, fieldname).read_only, 1, fieldname);
	}
	for (const fieldname of ["conversion_amount", "target_rate", "target_account", "target_party_type", "target_party"]) {
		assert.ok(!field(legMeta, fieldname).read_only, fieldname);
	}
	assert.equal(field(legMeta, "posting_exchange_rate").hidden, 1);
	assert.equal(field(legMeta, "fill_remaining").label, "کل مانده");
});

test("header labels are Persian, the Receipt is selectable and Company follows it", () => {
	assert.deepEqual(
		["source_receipt", "posting_date", "target_currency", "remarks"].map((fieldname) => field(conversionMeta, fieldname).label),
		["رسید مبدا", "تاریخ تبدیل", "ارز مقصد", "توضیحات"],
	);
	assert.ok(!field(conversionMeta, "source_receipt").read_only);
	assert.equal(field(conversionMeta, "company").read_only_depends_on, "eval:doc.conversion_mode!=='Balance'");
	assert.ok(!field(conversionMeta, "target_currency").read_only);
});

test("the Receipt only gains an unsaved-Conversion button", () => {
	const receiptForm = read(path.join(DOCTYPE_DIR, "smartprocess_accounting_document", "smartprocess_accounting_document.js"));
	assert.match(receiptForm, /add_custom_button\("تبدیل ارز", \(\) => startReceiptConversion\(frm\)\)/);
	assert.match(receiptForm, /frappe\.new_doc\(SP_RECEIPT_CONVERSION, \{ source_receipt: frm\.doc\.name, company: frm\.doc\.company \}\)/);
	assert.match(receiptForm, /frm\.doc\.docstatus === 1/);
	const conversionForm = read(path.join(CONVERSION_DIR, "conversion", "conversion_form.js"));
	assert.ok(!/\.save\(|\.savesubmit\(|\.submit\(/.test(conversionForm), "the form never saves or submits by itself");
	assert.ok(!/posting_exchange_rate/.test(conversionForm), "the hidden posting rate is never written");
	const doctypeScript = read(path.join(CONVERSION_DIR, "smartprocess_receipt_conversion.js"));
	for (const file of ["receipt/receipt_numbers.js", "conversion/conversion_legs.js", "conversion/conversion_form.js"]) {
		assert.ok(doctypeScript.includes(`${file}" %}`), file);
	}
});

function receiptForm(values = {}) {
	const shown = { indicators: [], buttons: [] };
	const frm = {
		doc: { name: "SP-REC-1", operation_type: "Receipt", docstatus: 1, ...values },
		dashboard: { add_indicator: (label, color) => shown.indicators.push([label, color]) },
		add_custom_button: (label, action) => shown.buttons.push([label, action]),
	};
	return { frm, shown };
}

test("Receipt status indicator uses the server status and Persian labels", async () => {
	const expected = {
		"Not Converted": ["تبدیل نشده", "gray"],
		"Partially Converted": ["تبدیل جزئی", "orange"],
		"Fully Converted": ["تبدیل کامل", "green"],
	};
	for (const [status, indicator] of Object.entries(expected)) {
		const { frm, shown } = receiptForm();
		responses.get_receipt_conversion_status = { status, linked_count: 0, active_count: 0 };
		await spReceiptConversionStatus.refresh(frm);
		assert.deepEqual(shown.indicators, [indicator]);
		assert.deepEqual(shown.buttons, [], "no linked Conversion, no list button");
	}
	assert.deepEqual(calls.xcall.at(-1).args, { source_receipt: "SP-REC-1" });
});

test("related Conversions button shows the active count and lists Receipt- and Balance-mode history", async () => {
	const { frm, shown } = receiptForm();
	const routes = [];
	frappe.set_route = (...args) => routes.push(args);
	const names = ["SP-RCONV-1", "SP-RCONV-2", "SP-RCONV-3"];
	responses.get_receipt_conversion_status = { status: "Partially Converted", linked_count: 3, active_count: 2, names };
	await spReceiptConversionStatus.refresh(frm);
	assert.equal(shown.buttons[0][0], "تبدیل‌های مرتبط (2)");
	shown.buttons[0][1]();
	assert.deepEqual(routes, [["List", "SmartProcess Receipt Conversion", { name: ["in", names] }]]);
	assert.equal(spReceiptConversionStatus.listLabel(0), "تبدیل‌های مرتبط", "only drafts/cancelled: no count");
	delete frappe.set_route;
});

test("status is shown only on a submitted Receipt and a stale response is dropped", async () => {
	for (const values of [{ docstatus: 0 }, { docstatus: 2 }, { operation_type: "Payment" }]) {
		const { frm, shown } = receiptForm(values);
		await spReceiptConversionStatus.refresh(frm);
		assert.deepEqual(shown.indicators, []);
	}
	assert.ok(!calls.xcall.some((call) => call.method.endsWith("get_receipt_conversion_status")));
	const { frm, shown } = receiptForm();
	let release;
	responses.get_receipt_conversion_status = () => new Promise((resolve) => (release = resolve));
	const first = spReceiptConversionStatus.refresh(frm);
	responses.get_receipt_conversion_status = { status: "Fully Converted", linked_count: 1, active_count: 1 };
	await spReceiptConversionStatus.refresh(frm);
	release({ status: "Not Converted", linked_count: 0, active_count: 0 });
	await first;
	assert.deepEqual(shown.indicators, [["تبدیل کامل", "green"]]);
});

function balanceForm(values = {}) {
	const frm = form({
		conversion_mode: "Balance",
		source_receipt: null,
		target_currency: "USD",
		source_party_type: "Customer",
		source_party: "CUST-1",
		source_account: "Debtors - SP",
		...values,
	});
	frm.set_value = async (fieldname, value) => {
		Object.assign(frm.doc, typeof fieldname === "object" ? fieldname : { [fieldname]: value });
	};
	return frm;
}

const SUMMARY = {
	company_currency: "IRR",
	as_of_balance: "150000000",
	balance_side: "Credit",
	max_convertible: "100000000",
	suggestion: { target_party_type: "Customer", target_party: "CUST-USD", target_account: "Debtors USD - SP" },
};

test("Balance mode fields are Persian, separate from the Receipt grid and hide Receipt-only fields", () => {
	const labels = Object.fromEntries(conversionMeta.fields.map((df) => [df.fieldname, df.label]));
	assert.deepEqual(
		["balance_source_section", "as_of_balance", "max_convertible", "balance_conversion_section", "fill_max_convertible", "target_amount", "balance_target_section"].map((name) => labels[name]),
		["منبع", "مانده حساب", "حداکثر قابل تبدیل", "تبدیل", "کل مانده قابل تبدیل", "مبلغ مقصد", "مقصد"],
	);
	assert.equal(field(conversionMeta, "conversion_mode").default, "Receipt");
	assert.equal(field(conversionMeta, "source_receipt").depends_on, "eval:doc.conversion_mode!=='Balance'");
	assert.equal(field(conversionMeta, "legs").depends_on, "eval:doc.conversion_mode==='Balance' && doc.docstatus>0");
	assert.equal(field(conversionMeta, "posting_date").read_only_depends_on, "eval:doc.conversion_mode==='Balance'");
	for (const name of ["as_of_balance", "balance_side", "max_convertible", "target_amount"]) {
		assert.equal(field(conversionMeta, name).read_only, 1, name);
	}
	assert.deepEqual(conversionMeta.field_order.slice(1, 6), ["source_receipt", "company", "column_break_header", "posting_date", "target_currency"]);
});

test("the list shows mode, source Receipt, date, currency, source Party and amount with contextual mode labels", () => {
	const columns = conversionMeta.field_order.filter((name) => field(conversionMeta, name)?.in_list_view);
	assert.deepEqual(columns, ["conversion_mode", "source_receipt", "posting_date", "target_currency", "source_party", "conversion_amount"]);
	const csv = read(path.join(__dirname, "..", "..", "translations", "fa.csv"));
	assert.match(csv, /^SmartProcess Receipt Conversion,تبدیل ارز,$/m);
	assert.match(csv, /^Receipt,از رسید,SmartProcess Receipt Conversion$/m);
	assert.match(csv, /^Balance,از مانده حساب,SmartProcess Receipt Conversion$/m);
	assert.doesNotMatch(csv, /^Receipt,از رسید,$/m);

	const contexts = [];
	globalThis.__ = (text, args, context) => (contexts.push(context), { Balance: "از مانده حساب" }[text] || text);
	require(path.join(CONVERSION_DIR, "smartprocess_receipt_conversion_list.js"));
	assert.equal(frappe.listview_settings["SmartProcess Receipt Conversion"].formatters.conversion_mode("Balance"), "از مانده حساب");
	assert.deepEqual(contexts, ["SmartProcess Receipt Conversion"]);
	delete globalThis.__;
});

test("Balance summary comes from the server, keeps balance and maximum apart and prefills only an empty target", async () => {
	const frm = balanceForm();
	responses.get_balance_summary = SUMMARY;
	await spBalanceForm.loadSummary(frm);
	assert.deepEqual(calls.xcall.at(-1).args, {
		company: "SP",
		source_party_type: "Customer",
		source_party: "CUST-1",
		source_account: "Debtors - SP",
		posting_date: null,
		target_currency: "USD",
	});
	assert.deepEqual([frm.doc.as_of_balance, frm.doc.max_convertible, frm.doc.balance_side], [150000000, 100000000, "Credit"]);
	assert.equal(frm.tableProperties["max_convertible:description"], spBalanceForm.MESSAGES.partial);
	assert.equal(frm.doc.target_account, "Debtors USD - SP");
	frm.doc.target_account = "My USD - SP";
	frm.doc.target_party = "";
	await spBalanceForm.loadSummary(frm);
	assert.equal(frm.doc.target_account, "My USD - SP", "a user target is never replaced");
});

test("Balance summary errors are shown on the source and a stale answer is dropped", async () => {
	const frm = balanceForm();
	responses.get_balance_summary = { error: "Source Account must be in the Company currency IRR." };
	await spBalanceForm.loadSummary(frm);
	assert.deepEqual([frm.doc.as_of_balance ?? null, frm.doc.max_convertible ?? null], [null, null]);
	assert.match(frm.tableProperties["source_account:description"], /Company currency/);
	let release;
	responses.get_balance_summary = () => new Promise((resolve) => (release = resolve));
	const first = spBalanceForm.loadSummary(frm);
	responses.get_balance_summary = { ...SUMMARY, max_convertible: "150000000", suggestion: null };
	await spBalanceForm.loadSummary(frm);
	release({ ...SUMMARY, max_convertible: "1" });
	await first;
	assert.equal(frm.doc.max_convertible, 150000000);
	assert.equal(frm.tableProperties["max_convertible:description"], "", "equal balance and maximum: no note");
});

test("the full-maximum button uses max_convertible, never the account balance", async () => {
	const frm = balanceForm({ as_of_balance: 150000000, max_convertible: 100000000 });
	await spBalanceForm.fillMax(frm);
	assert.equal(frm.doc.conversion_amount, 100000000);
	const submitted = balanceForm({ docstatus: 1, max_convertible: 5, conversion_amount: 1 });
	await spBalanceForm.fillMax(submitted);
	assert.equal(submitted.doc.conversion_amount, 1);
});

test("the Balance Target Amount is a server preview and the rate is never written", async () => {
	const frm = balanceForm({ conversion_amount: 100000000, target_rate: 90000 });
	await spBalanceForm.preview(frm);
	const call = calls.xcall.at(-1);
	assert.ok(call.method.endsWith("receipt_conversion_api.preview_target_amounts"));
	assert.deepEqual(call.args.legs, [{ name: "total", conversion_amount: 100000000, target_rate: 90000 }]);
	assert.deepEqual([frm.doc.target_amount, frm.doc.target_rate], [1111.11, 90000]);
});

test("Receipt-mode legs never load for a Balance Conversion", async () => {
	const frm = balanceForm();
	responses.get_company_currency = "IRR";
	responses.get_balance_summary = { ...SUMMARY, suggestion: null };
	await spConversionForm.refresh(frm);
	await spBalanceForm.refresh(frm);
	assert.ok(!calls.xcall.some((call) => call.method.endsWith("get_conversion_legs")));
	assert.equal(frm.tableProperties["legs:read_only"], 1);
	assert.equal(frm.tableProperties["legs:label"], spBalanceForm.MESSAGES.legsLabel);
	assert.deepEqual(frm.tableProperties["conversion_mode:options"].map((option) => option.label), ["از رسید", "از مانده حساب"]);
});

test("Receipt mode has separate Receiver and Payer sections before the stored legs table", () => {
	const order = conversionMeta.field_order;
	const at = (fieldname) => order.indexOf(fieldname);
	assert.ok(at("receiver_conversion_section") < at("payer_conversion_section"));
	assert.ok(at("payer_conversion_section") < at("legs_section"));
	assert.deepEqual(
		["receiver_conversion_section", "payer_conversion_section"].map((fieldname) => field(conversionMeta, fieldname).label),
		["تبدیل دریافت‌کننده", "تبدیل پرداخت‌کنندگان"],
	);
	for (const fieldname of ["receiver_conversion_section", "payer_conversion_section"]) {
		assert.equal(field(conversionMeta, fieldname).depends_on, "eval:doc.conversion_mode!=='Balance'");
	}
	assert.equal(field(conversionMeta, "receiver_conversion_html").fieldtype, "HTML");
	assert.equal(field(conversionMeta, "payer_conversion_html").fieldtype, "HTML");
});

test("each side shows only its own rows and Balance mode shows none", async () => {
	const frm = form();
	await selectCurrency(frm, "USD");
	assert.deepEqual(spConversionSides.rows(frm, "Receiver").map((row) => row.source_side), ["Receiver"]);
	assert.deepEqual(spConversionSides.rows(frm, "Payer").map((row) => row.source_side), ["Payer"]);
	frm.doc.conversion_mode = "Balance";
	assert.deepEqual(spConversionSides.rows(frm, "Receiver"), []);
});

test("the side grids edit only target columns; source columns stay out of the grid", () => {
	const fields = spConversionSides.editableFields();
	assert.deepEqual(
		fields.map((df) => df.fieldname),
		["conversion_amount", "target_rate", "target_amount", "target_party_type", "target_party", "target_account"],
	);
	for (const fieldname of [...spConversionLegs.SOURCE_FIELDS]) {
		assert.ok(!fields.some((df) => df.fieldname === fieldname), fieldname);
	}
	assert.ok(fields.reduce((total, df) => total + df.columns, 0) <= 10);
	assert.equal(field(legMeta, "target_amount").read_only, 1);
});

test("source info is a read-only block with party, account and amounts; fill only in draft", () => {
	const rows = [{ name: "leg-2", idx: 2, ...serverLeg("Payer", { already_converted: "40000000", remaining_amount: "60000000" }) }];
	const options = {
		editable: true,
		format: (fieldname, row) => `#${row[fieldname]}`,
		titleOf: (partyType, party) => (party === "CUST-1" ? "مشتری یک" : ""),
	};
	const html = spConversionSides.sourceHtml(rows, "Payer", options);
	for (const text of ["پرداخت‌کننده", "مشتری یک", "Debtors - SP", "#100000000", "#40000000", "#60000000", "حساب مبدا", "مانده قابل تبدیل"]) {
		assert.ok(html.includes(text), text);
	}
	assert.ok(html.includes('data-sp-fill="leg-2"'));
	assert.ok(!html.includes("<input"));
	assert.ok(!spConversionSides.sourceHtml(rows, "Payer", { ...options, editable: false }).includes("data-sp-fill"));
	assert.ok(spConversionSides.sourceHtml([], "Receiver", options).includes("رسید مبدا"));
	const unsafe = [{ ...rows[0], source_account: "<b>x</b>" }];
	assert.ok(!spConversionSides.sourceHtml(unsafe, "Payer", options).includes("<b>x</b>"));
});

test("standard Link queries: submitted Receipts, target-currency Accounts, Party independent of the source", () => {
	const queries = {};
	const frm = form({ target_currency: "USD" });
	frm.set_query = (fieldname, table, fn) => (queries[fieldname] = typeof table === "function" ? table : fn);
	spConversionForm.setup(frm);
	assert.equal(field(conversionMeta, "source_receipt").fieldtype, "Link");
	assert.equal(field(conversionMeta, "source_receipt").options, "SmartProcess Accounting Document");
	assert.deepEqual(queries.source_receipt().filters, { operation_type: "Receipt", docstatus: 1 });
	assert.match(read(path.join(CONVERSION_DIR, "smartprocess_receipt_conversion.js")), /source_receipt\(frm\)\s*\{\s*return spConversionForm\.receiptChanged\(frm\);/);
	const row = { doctype: LEG, name: "leg-q", ...serverLeg("Payer"), target_party_type: "Supplier", target_party: "SUP-7" };
	docs.set(row.name, row);
	const account = queries.target_account(frm.doc, LEG, row.name).filters;
	assert.deepEqual(account, { company: "SP", disabled: 0, is_group: 0, account_currency: "USD", account_type: "Payable" });
	const party = queries.target_party(frm.doc, LEG, row.name);
	assert.deepEqual(party.filters, { party_type: "Supplier", company: "SP", currency: "USD" });
	assert.ok(!JSON.stringify([account, party]).includes(row.source_party));
});

test("a mixed Receipt shows one passive note that foreign-currency sides are left out", async () => {
	const frm = form({ target_currency: "USD" });
	responses.get_conversion_legs = { legs: [serverLeg("Receiver")], titles: {}, foreign_sides: 1 };
	await spConversionForm.receiptChanged(frm);
	await settle();
	assert.equal(frm.tableProperties["source_receipt:description"], spConversionForm.MESSAGES.foreignSides);
	assert.match(spConversionForm.MESSAGES.foreignSides, /فقط ردیف‌های با ارز پایه شرکت/);
	assert.deepEqual([calls.confirm.length, calls.alerts.length], [0, 0]);
	responses.get_conversion_legs = () => ({ legs: [serverLeg("Receiver"), serverLeg("Payer")], titles: {}, foreign_sides: 0 });
	await spConversionForm.receiptChanged(frm);
	await settle();
	assert.equal(frm.tableProperties["source_receipt:description"], "");
});

test("each side numbers its rows from 1 without touching the stored idx", () => {
	const rows = [{ name: "leg-2", idx: 2, ...serverLeg("Payer") }];
	const html = spConversionSides.sourceHtml(rows, "Payer", { editable: false, format: () => "", titleOf: () => "" });
	assert.match(html, /<tbody><tr><td>1<\/td>/);
	const shown = {};
	const gridRow = (doc) => {
		const row = {
			doc,
			wrapper: { find: () => ({ text: (value) => (shown[doc.name] = value) }) },
			set_row_index() {
				shown[doc.name] = doc.idx;
			},
		};
		return row;
	};
	const grid = { grid_rows: [gridRow({ name: "leg-2", idx: 2 }), gridRow({ name: "leg-4", idx: 4 })] };
	spConversionSides.numberRows(grid);
	assert.deepEqual(shown, { "leg-2": 1, "leg-4": 2 });
	grid.grid_rows[1].set_row_index();
	assert.equal(shown["leg-4"], 2);
	assert.deepEqual(grid.grid_rows.map((row) => row.doc.idx), [2, 4]);
});

test("the Workspace and sidebar open the Receipt Conversion as «تبدیل ارز»", () => {
	const workspace = JSON.parse(read(path.join(__dirname, "..", "workspace", "smartprocess_accounting", "smartprocess_accounting.json")));
	const links = workspace.links.filter((link) => link.type === "Link");
	assert.deepEqual(
		links.filter((link) => link.label === "تبدیل ارز").map((link) => [link.link_type, link.link_to]),
		[["DocType", "SmartProcess Receipt Conversion"]],
	);
	assert.ok(!links.some((link) => link.link_to === "SmartProcess Currency Conversion"));
	const install = read(path.join(__dirname, "..", "..", "install.py"));
	assert.match(install, /\("تبدیل ارز", "DocType", "SmartProcess Receipt Conversion", None\)/);
});

test("choosing a Receipt directly loads its rows once the target currency is known", async () => {
	const frm = form({ source_receipt: "", target_currency: "USD" });
	frm.doc.source_receipt = "SP-REC-2";
	await spConversionForm.receiptChanged(frm);
	await settle();
	assert.deepEqual(calls.xcall[0].args, { source_receipt: "SP-REC-2", target_currency: "USD" });
	assert.equal(frm.doc.legs.length, 2);
	assert.equal(calls.confirm.length, 0);
	const empty = form();
	await spConversionForm.receiptChanged(empty);
	assert.ok(!calls.xcall.some((call) => call.args?.source_receipt === "SP-REC-1"));
});

test("a new Receipt replaces every row and target input from the previous one", async () => {
	const frm = form();
	await selectCurrency(frm, "USD");
	Object.assign(frm.doc.legs[1], { conversion_amount: 5, target_rate: 90000, target_party: "CUST-9" });
	responses.get_conversion_legs = { legs: [serverLeg("Receiver", { source_pair: "pair-2" })], titles: {} };
	frm.doc.source_receipt = "SP-REC-2";
	await spConversionForm.receiptChanged(frm);
	await settle();
	assert.deepEqual(frm.doc.legs.map((leg) => [leg.source_pair, leg.conversion_amount, leg.target_party]), [["pair-2", 0, undefined]]);
	assert.equal(calls.confirm.length, 0);
});

test("an ineligible Receipt shows the server message inline and loads no rows", async () => {
	const frm = form({ target_currency: "USD" });
	responses.get_conversion_legs = { error: "رسید SP-REC-1 سمتی به ارز پایه شرکت (IRR) برای تبدیل ندارد.", legs: [], titles: {} };
	await spConversionForm.receiptChanged(frm);
	await settle();
	assert.deepEqual(frm.doc.legs, []);
	assert.match(frm.tableProperties["source_receipt:description"], /سمتی به ارز پایه/);
	assert.equal(calls.confirm.length, 0);
	assert.equal(calls.alerts.length, 0);
	responses.get_conversion_legs = () => ({ legs: [serverLeg("Receiver")], titles: {} });
	await spConversionForm.receiptChanged(frm);
	await settle();
	assert.equal(frm.tableProperties["source_receipt:description"], "");
});

test("the Conversion adopts the Company of the chosen Receipt", async () => {
	const frm = form({ target_currency: "USD" });
	responses.get_company_currency = "IRR";
	responses.get_conversion_legs = { company: "SP-2", legs: [serverLeg("Receiver")], titles: {} };
	await spConversionForm.receiptChanged(frm);
	await settle();
	assert.equal(frm.doc.company, "SP-2");
});

test("targets are independent: no source Party is copied and accounts follow the target currency", async () => {
	const frm = form();
	responses.get_conversion_legs = { legs: [serverLeg("Receiver"), serverLeg("Payer")], titles: {} };
	await selectCurrency(frm, "USD");
	const payer = frm.doc.legs[1];
	assert.equal(payer.source_party, "CUST-1");
	assert.equal(payer.target_party_type, undefined);
	assert.equal(payer.target_party, undefined);
	assert.equal(payer.target_account, undefined);
	assert.equal(spConversionLegs.accountFilters("SP", "USD", "Supplier", "SUP-7").account_currency, "USD");
	assert.equal(spConversionLegs.accountFilters("SP", "USD", "Supplier", "SUP-7").account_type, "Payable");
});

test("typing in the side grids never asks for a confirmation", async () => {
	const frm = form();
	await selectCurrency(frm, "USD");
	const row = frm.doc.legs[1];
	for (const value of [1, 12, 123]) {
		row.conversion_amount = value;
		spConversionForm.amountChanged(frm, LEG, row.name);
		row.target_rate = value * 10;
		spConversionForm.rateChanged(frm, LEG, row.name);
	}
	await settle();
	assert.equal(calls.confirm.length, 0);
	assert.equal(calls.alerts.length, 0);
});

(async () => {
	for (const [name, run] of tests) {
		reset();
		await run();
		console.log(`ok - ${name}`);
	}
	console.log(`receipt_conversion_ui: ${tests.length} tests passed`);
})().catch((error) => {
	console.error(error);
	process.exitCode = 1;
});
