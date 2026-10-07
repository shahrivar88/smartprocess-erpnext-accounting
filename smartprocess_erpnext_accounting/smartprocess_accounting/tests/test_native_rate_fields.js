// Pure tests for the native ERPNext rate fields: Frappe is stubbed, nothing touches a site.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const APP_DIR = path.join(__dirname, "..", "..");
const ACCOUNTING_DIR = path.join(__dirname, "..");

const registrations = [];
globalThis.window = globalThis;
globalThis.frappe = {
	boot: {},
	meta: { docfield_map: {} },
	ui: { form: { on: (doctype, events) => registrations.push([doctype, events]) } },
};
globalThis.erpnext = { get_currency: (company) => ({ SP: "IRR" })[company] };
globalThis.get_number_format = () => "#,###.##";
globalThis.get_number_format_info = () => ({ decimal_str: ".", group_str: "," });
require(path.join(APP_DIR, "public", "js", "smartprocess_numeric.js"));
const native = require(path.join(APP_DIR, "public", "js", "native_rate_fields.js"));

const tests = [];
const test = (name, run) => tests.push([name, run]);

function flags(values) {
	frappe.boot = { smartprocess_accounting: { allow_exchange_rate_editing: 1, ...values } };
}

function metaFor(doctype, fields) {
	frappe.meta.docfield_map[doctype] = Object.fromEntries(
		fields.map((fieldname) => [fieldname, { fieldname, read_only: 0, permlevel: 0 }]),
	);
}

function form(doctype, values = {}, write = 1) {
	const calls = [];
	const frm = {
		doctype,
		doc: { doctype, docstatus: 0, company: "SP", currency: "USD", ...values },
		perm: [{ write }],
		set_value: () => calls.push("set_value"),
		dirty: () => calls.push("dirty"),
		set_df_property(fieldname, property, value) {
			calls.push([fieldname, property, value]);
		},
	};
	native.guardRateLock(frm);
	return { frm, calls };
}

const lock = (doctype, values, fieldname = "conversion_rate", write = 1) => {
	const { frm, calls } = form(doctype, values, write);
	frm.set_df_property(fieldname, "read_only", 1);
	return calls.at(-1)[2];
};

test("1 each native DocType registers its handlers once, however often the file runs", () => {
	native.register(frappe);
	native.register(frappe);
	assert.deepEqual(registrations.map(([doctype]) => doctype), [
		"Sales Invoice",
		"Purchase Invoice",
		"Payment Entry",
		"Sales Invoice Item",
		"Purchase Invoice Item",
	]);
	for (const [doctype, events] of registrations) {
		assert.deepEqual(Object.keys(events), doctype.endsWith(" Item") ? ["form_render"] : ["setup", "refresh"]);
	}
});

test("2 the stale-rate lock is skipped only for an editable foreign Draft rate", () => {
	metaFor("Sales Invoice", ["conversion_rate"]);
	metaFor("Purchase Invoice", ["conversion_rate"]);
	flags();
	assert.equal(lock("Sales Invoice", {}), 0);
	assert.equal(lock("Purchase Invoice", {}), 0);
	assert.equal(lock("Sales Invoice", { currency: "IRR" }), 1, "a Company-currency rate stays 1 and locked");
	assert.equal(lock("Sales Invoice", { docstatus: 1 }), 1, "submitted");
	assert.equal(lock("Sales Invoice", { docstatus: 2 }), 1, "cancelled");
	assert.equal(lock("Sales Invoice", {}, "conversion_rate", 0), 1, "no write permission");
	assert.equal(lock("Sales Invoice", {}, "plc_conversion_rate"), 1, "only the listed rate fields");
	frappe.meta.docfield_map["Sales Invoice"].conversion_rate.read_only = 1;
	assert.equal(lock("Sales Invoice", {}), 1, "a DocType read-only rate stays read-only");
	frappe.meta.docfield_map["Sales Invoice"].conversion_rate.read_only = 0;
	flags({ allow_exchange_rate_editing: 0 });
	assert.equal(lock("Sales Invoice", {}), 1, "setting off: ERPNext behavior unchanged");
});

test("3 Payment Entry rates follow their own account currency", () => {
	metaFor("Payment Entry", ["source_exchange_rate", "target_exchange_rate"]);
	flags();
	const values = { paid_from_account_currency: "USD", paid_to_account_currency: "IRR" };
	assert.equal(lock("Payment Entry", values, "source_exchange_rate"), 0);
	assert.equal(lock("Payment Entry", values, "target_exchange_rate"), 1);
	assert.equal(lock("Payment Entry", { ...values, paid_to_account_currency: "EUR" }, "target_exchange_rate"), 0);
});

test("4 other properties and calls pass through; the guard wraps once and never writes", () => {
	metaFor("Sales Invoice", ["conversion_rate"]);
	flags();
	const { frm, calls } = form("Sales Invoice");
	const wrapped = frm.set_df_property;
	native.guardRateLock(frm);
	assert.equal(frm.set_df_property, wrapped, "installs once per form");
	const before = JSON.stringify(frm.doc);
	frm.set_df_property("conversion_rate", "reqd", 1);
	frm.set_df_property("conversion_rate", "read_only", 0);
	frm.set_df_property("posting_date", "read_only", 1);
	assert.deepEqual(calls, [["conversion_rate", "reqd", 1], ["conversion_rate", "read_only", 0], ["posting_date", "read_only", 1]]);
	assert.equal(JSON.stringify(frm.doc), before, "no rate or document value changes");
});

function control(value, formatted) {
	const listeners = [];
	const element = { addEventListener: (type) => listeners.push(type) };
	const inputs = [];
	return {
		value,
		listeners,
		inputs,
		$input: { get: () => element },
		parse: (text) => parseFloat(text),
		set_formatted_input(raw) {
			inputs.push(raw);
		},
		format_for_input: () => formatted,
	};
}

test("5 rate inputs drop trailing zeros in the display only", () => {
	flags({ hide_insignificant_trailing_zeros: 1, live_number_separator: { enabled: 1 } });
	const on = control(15000, "15,000.000000000");
	native.prepareInput(on);
	assert.equal(on.format_for_input(15000), "15,000");
	assert.equal(on.value, 15000, "control value stays the raw number");
	assert.deepEqual(on.inputs, [15000], "re-rendered from the raw value");
	assert.equal(on.parse("1,500,000.5"), 1500000.5);
	flags({ hide_insignificant_trailing_zeros: 0, live_number_separator: { enabled: 0 } });
	const off = control(15000, "15,000.000000000");
	native.prepareInput(off);
	assert.equal(off.format_for_input(15000), "15,000.000000000", "setting off: standard Frappe display");
	assert.deepEqual(off.inputs, []);
	assert.ok(Number.isNaN(off.parse("abc")), "parse is the original one in effect");
});

test("6 repeated refresh prepares every rate control once", () => {
	flags({ hide_insignificant_trailing_zeros: 1, live_number_separator: { enabled: 1 } });
	const source = control(1, "1.000000000");
	const target = control(1, "1.000000000");
	const { frm, calls } = form("Payment Entry");
	frm.fields_dict = { source_exchange_rate: source, target_exchange_rate: target };
	for (let i = 0; i < 3; i += 1) {
		native.prepareRateInputs(frm);
	}
	assert.deepEqual([source.listeners, target.listeners], [["input"], ["input"]]);
	assert.deepEqual(calls, [], "no set_value, dirty flag or property change");
});

test("7 SmartProcess forms keep their own rate locks; only UI code reads the setting", () => {
	assert.ok(Object.keys(native.RATE_FIELDS).every((doctype) => !doctype.startsWith("SmartProcess")));
	const clientFiles = [];
	const walk = (dir) => {
		for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
			const full = path.join(dir, entry.name);
			if (entry.isDirectory()) walk(full);
			else if (entry.name.endsWith(".js") && !full.includes(`${path.sep}tests${path.sep}`)) clientFiles.push(full);
		}
	};
	walk(path.join(ACCOUNTING_DIR, "doctype"));
	for (const file of clientFiles) {
		assert.ok(!fs.readFileSync(file, "utf-8").includes("allow_exchange_rate_editing"), file);
	}
	const hooks = fs.readFileSync(path.join(APP_DIR, "hooks.py"), "utf-8");
	for (const doctype of Object.keys(native.RATE_FIELDS)) {
		assert.match(hooks, new RegExp(`"${doctype}": [^\\n]*native_rate_fields\\.js`), doctype);
	}
	const source = fs.readFileSync(path.join(APP_DIR, "public", "js", "native_rate_fields.js"), "utf-8");
	for (const forbidden of ["prototype", "eval(", "set_value(", "innerHTML", ".html("]) {
		assert.ok(!source.includes(forbidden), forbidden);
	}
});

(async () => {
	for (const [name, run] of tests) {
		await run();
		console.log(`ok - ${name}`);
	}
	console.log(`native_rate_fields: ${tests.length} tests passed`);
})().catch((error) => {
	console.error(error);
	process.exitCode = 1;
});
