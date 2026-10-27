// Pure tests for the numeric display of native invoice item grids: Frappe and the
// grid are stubbed, nothing touches a site.
const assert = require("node:assert/strict");
const path = require("node:path");

const APP_DIR = path.join(__dirname, "..", "..");

globalThis.window = globalThis;
globalThis.frappe = { boot: {}, meta: { docfield_map: {} }, ui: { form: {} } };
globalThis.get_number_format = () => "#,###.##";
globalThis.get_number_format_info = () => ({ decimal_str: ".", group_str: "," });
globalThis.locals = {};
const wrapperHandlers = [];
globalThis.jQuery = (target) => ({
	on: (event, handler) => wrapperHandlers.push({ target, event, handler }),
});
require(path.join(APP_DIR, "public", "js", "smartprocess_numeric.js"));
const native = require(path.join(APP_DIR, "public", "js", "native_rate_fields.js"));

const tests = [];
const test = (name, run) => tests.push([name, run]);

function settings({ trailing = 1, live = 1 } = {}) {
	frappe.boot = {
		smartprocess_accounting: {
			hide_insignificant_trailing_zeros: trailing,
			live_number_separator: { enabled: live, separator: ",", decimal_str: ".", group_str: "," },
		},
	};
}

// Native format_number() output: always `precision` decimals, "," groups.
function frappeNumber(value, precision) {
	const [integer, fraction] = Math.abs(value).toFixed(precision).split(".");
	const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
	return (value < 0 ? "-" : "") + grouped + (fraction ? `.${fraction}` : "");
}

// A Frappe cell control: format_for_input pads to precision, parse is a plain
// parseFloat (so a grouped text only parses right after our cleaning).
function cellControl(row, fieldname, fieldtype = "Float", precision = 2) {
	const listeners = [];
	const element = {
		value: "",
		selectionStart: null,
		addEventListener: (type, handler) => listeners.push([type, handler]),
		setSelectionRange() {},
	};
	return {
		df: { fieldname, fieldtype, precision },
		doc: row,
		element,
		listeners,
		$input: { get: () => element },
		get_value: () => row[fieldname],
		parse: (text) => {
			const number = parseFloat(text);
			return Number.isNaN(number) ? null : number;
		},
		format_for_input(value) {
			return value === null || value === undefined ? "" : frappeNumber(value, precision);
		},
		set_formatted_input(value) {
			element.value = this.format_for_input(value);
		},
	};
}

const FIELD_TYPES = {
	qty: ["Float", 2],
	conversion_factor: ["Float", 9],
	rate: ["Currency", 2],
	amount: ["Currency", 2],
	discount_percentage: ["Percent", 2],
	item_code: ["Link", undefined],
	weight_per_unit: ["Float", 2],
};

// An invoice form with one item row; make_control builds the cell control the
// way GridRow does (lazily, once per column).
function invoice(doctype = "Sales Invoice", values = {}, table = "items") {
	const row = { doctype: `${doctype} Item`, name: "row-1", parentfield: table, ...values };
	locals[row.doctype] = { [row.name]: row };
	const calls = [];
	const frm = {
		doctype,
		wrapper: { id: doctype },
		doc: { doctype, docstatus: 0, [table]: [row] },
		set_value: () => calls.push("set_value"),
		dirty: () => calls.push("dirty"),
		fields_dict: {},
	};
	const grid = { frm, df: { fieldname: table } };
	const gridRow = {
		grid,
		doc: row,
		on_grid_fields: [],
		on_grid_fields_dict: {},
		builds: 0,
		make_control(column) {
			if (column.field) return;
			this.builds += 1;
			const [fieldtype, precision] = FIELD_TYPES[column.df.fieldname];
			const field = cellControl(row, column.df.fieldname, fieldtype, precision);
			field.refresh = () => field.set_formatted_input(field.get_value());
			field.refresh();
			column.field = field;
			this.on_grid_fields_dict[column.df.fieldname] = field;
			this.on_grid_fields.push(field);
		},
	};
	grid.grid_rows = [gridRow];
	grid.get_row = (key) => (key === row.name ? gridRow : null);
	frm.fields_dict[table] = { grid };
	return { frm, row, gridRow, calls };
}

function cell(gridRow, fieldname) {
	const column = { df: { fieldname } };
	gridRow.make_control(column);
	return column.field;
}

const typeInto = (control, text) => {
	control.element.value = text;
	control.element.selectionStart = text.length;
	for (const [type, handler] of control.listeners) {
		if (type === "input") handler();
	}
	return control.element.value;
};

const CASES = [
	["qty", 10, "10"],
	["qty", 10.5, "10.5"],
	["qty", 10.05, "10.05"],
	["rate", 1000, "1,000"],
	["rate", 1000.5, "1,000.5"],
	["amount", 1000000, "1,000,000"],
	["rate", -1000.5, "-1,000.5"],
	["amount", -1000000, "-1,000,000"],
	["qty", 0, "0"],
	["rate", 0.05, "0.05"],
	["conversion_factor", 0.000123, "0.000123"],
	["conversion_factor", 1, "1"],
	["discount_percentage", 12.5, "12.5"],
];

test("1 item cells show insignificant zeros dropped; the raw row value never changes", () => {
	settings();
	for (const doctype of ["Sales Invoice", "Purchase Invoice", "Quotation", "Sales Order", "Purchase Order"]) {
		for (const [fieldname, value, visible] of CASES) {
			const { frm, row, gridRow, calls } = invoice(doctype, { [fieldname]: value });
			native.prepareItemGrids(frm);
			const before = JSON.stringify(row);
			const control = cell(gridRow, fieldname);
			assert.equal(control.element.value, visible, `${doctype} ${fieldname} ${value}`);
			assert.equal(control.format_for_input(value), visible);
			assert.equal(JSON.stringify(row), before, "row values unchanged");
			assert.equal(row[fieldname], value, "raw value identical");
			assert.equal(typeof row[fieldname], "number");
			assert.deepEqual(calls, [], "no set_value and no dirty flag");
		}
	}
});

test("2 settings off: the standard Frappe input text is kept", () => {
	settings({ trailing: 0, live: 0 });
	const { frm, row, gridRow } = invoice("Sales Invoice", { qty: 10, rate: 100000 });
	native.prepareItemGrids(frm);
	assert.equal(cell(gridRow, "qty").element.value, "10.00");
	const rate = cell(gridRow, "rate");
	assert.equal(rate.element.value, "100,000.00");
	assert.equal(typeInto(rate, "1000000"), "1000000", "no live grouping");
	assert.deepEqual([row.qty, row.rate], [10, 100000]);
});

test("3 live separator in an inline cell: grouped text, raw numeric parse", () => {
	settings({ trailing: 1, live: 1 });
	const { frm, row, gridRow, calls } = invoice("Sales Invoice", { rate: 0 });
	native.prepareItemGrids(frm);
	const rate = cell(gridRow, "rate");
	assert.equal(typeInto(rate, "1000000"), "1,000,000");
	assert.equal(rate.parse(rate.element.value), 1000000);
	assert.equal(typeInto(rate, "1000000.5"), "1,000,000.5");
	assert.equal(rate.parse(rate.element.value), 1000000.5);
	assert.equal(row.rate, 0, "typing alone writes nothing to the row");
	assert.deepEqual(calls, []);
	settings({ trailing: 1, live: 0 });
	const off = invoice("Sales Invoice", { rate: 0 });
	native.prepareItemGrids(off.frm);
	assert.equal(typeInto(cell(off.gridRow, "rate"), "1000000"), "1000000", "live off: untouched");
});

test("4 the expanded row editor gets the same display and live separator", () => {
	settings();
	const { frm, row, gridRow } = invoice("Purchase Invoice", { qty: 10, rate: 100000, amount: 1000000 });
	gridRow.grid_form = {
		fields_dict: {
			qty: cellControl(row, "qty"),
			rate: cellControl(row, "rate", "Currency"),
			amount: cellControl(row, "amount", "Currency"),
			item_code: cellControl(row, "item_code", "Link"),
		},
	};
	const before = JSON.stringify(row);
	native.prepareRowForm(frm, row.doctype, row.name);
	const form = gridRow.grid_form.fields_dict;
	assert.deepEqual(
		[form.qty.element.value, form.rate.element.value, form.amount.element.value],
		["10", "100,000", "1,000,000"],
	);
	assert.equal(typeInto(form.rate, "2500000"), "2,500,000");
	assert.equal(form.rate.parse(form.rate.element.value), 2500000);
	assert.equal(form.item_code.listeners.length, 0, "non-numeric fields untouched");
	assert.equal(JSON.stringify(row), before);
});

test("5 repeated refresh and re-render never duplicate wrappers or listeners", () => {
	settings();
	const { frm, gridRow } = invoice("Sales Invoice", { qty: 10 });
	native.watchItemGrids(frm);
	native.watchItemGrids(frm);
	const bound = wrapperHandlers.filter((entry) => entry.target === frm.wrapper);
	assert.equal(bound.length, 1, "one grid-row-render handler per form");
	assert.equal(bound[0].event, "grid-row-render");
	bound[0].handler({}, gridRow);
	const wrapped = gridRow.make_control;
	for (let i = 0; i < 3; i += 1) {
		native.prepareItemGrids(frm);
		bound[0].handler({}, gridRow);
	}
	assert.equal(gridRow.make_control, wrapped, "make_control wrapped once");
	const column = { df: { fieldname: "qty" } };
	gridRow.make_control(column);
	gridRow.make_control(column);
	const qty = column.field;
	native.prepareItemGrids(frm);
	native.prepareRowForm(frm, gridRow.doc.doctype, gridRow.doc.name);
	assert.equal(gridRow.builds, 1);
	assert.equal(qty.listeners.filter(([type]) => type === "input").length, 1);
	assert.equal(qty.element.value, "10");
});

test("6 only listed numeric fields of invoice item tables are prepared", () => {
	settings();
	const { frm, gridRow } = invoice("Sales Invoice", { item_code: "X", weight_per_unit: 2 });
	native.prepareItemGrids(frm);
	assert.equal(cell(gridRow, "item_code").listeners.length, 0);
	const weight = cell(gridRow, "weight_per_unit");
	assert.equal(weight.element.value, "2.00", "an unlisted Float keeps the standard display");
	const other = invoice("Payment Entry", { qty: 10 }, "references");
	native.prepareItemGrids(other.frm);
	native.prepareGridRow(other.gridRow);
	assert.equal(cell(other.gridRow, "qty").element.value, "10.00", "other DocTypes untouched");
	const taxes = invoice("Sales Invoice", { amount: 5 }, "taxes");
	native.prepareGridRow(taxes.gridRow);
	assert.equal(cell(taxes.gridRow, "amount").element.value, "5.00", "other tables untouched");
});

test("7 amounts stay ERPNext's; precision metadata is never written", () => {
	settings();
	const docfields = { qty: { precision: "" }, rate: { precision: "2" }, amount: { precision: "2" } };
	frappe.meta.docfield_map["Sales Invoice Item"] = docfields;
	const metaBefore = JSON.stringify(docfields);
	const { frm, row, gridRow } = invoice("Sales Invoice", { qty: 0, rate: 0, amount: 0 });
	native.prepareItemGrids(frm);
	const controls = ["qty", "rate", "amount"].map((fieldname) => cell(gridRow, fieldname));
	const precisions = controls.map((control) => control.df.precision);
	// ERPNext's own calculation, then the refresh Frappe runs after it.
	row.qty = 10;
	row.rate = 100000;
	row.amount = row.qty * row.rate;
	controls.forEach((control) => control.refresh());
	assert.deepEqual(
		controls.map((control) => control.element.value),
		["10", "100,000", "1,000,000"],
	);
	assert.deepEqual([row.qty, row.rate, row.amount], [10, 100000, 1000000]);
	assert.deepEqual(controls.map((control) => control.df.precision), precisions);
	assert.equal(JSON.stringify(docfields), metaBefore);
	assert.equal(typeof native.ITEM_NUMERIC_FIELDS.has, "function");
	assert.deepEqual(Object.keys(native.ITEM_GRIDS), [
		"Sales Invoice",
		"Purchase Invoice",
		"Quotation",
		"Sales Order",
		"Purchase Order",
	]);
});

test("8 a disabled DocType keeps the standard Frappe input even when the master flag is on", () => {
	frappe.boot = {
		smartprocess_accounting: {
			hide_insignificant_trailing_zeros: 1,
			live_number_separator: { enabled: 1, separator: ",", decimal_str: ".", group_str: "," },
			hide_trailing_zeros_doctypes: { "Sales Invoice": 0, Quotation: 1 },
			live_separator_doctypes: { "Sales Invoice": 0, Quotation: 1 },
		},
	};
	const off = invoice("Sales Invoice", { qty: 10, rate: 100000 });
	native.prepareItemGrids(off.frm);
	assert.equal(cell(off.gridRow, "qty").element.value, "10.00");
	const offRate = cell(off.gridRow, "rate");
	assert.equal(offRate.element.value, "100,000.00");
	assert.equal(typeInto(offRate, "1000000"), "1000000", "live off for this DocType");
	const on = invoice("Quotation", { qty: 10, rate: 100000 });
	native.prepareItemGrids(on.frm);
	assert.equal(cell(on.gridRow, "qty").element.value, "10");
	assert.equal(typeInto(cell(on.gridRow, "rate"), "1000000"), "1,000,000");
});

(async () => {
	for (const [name, run] of tests) {
		await run();
		console.log(`ok - ${name}`);
	}
	console.log(`native_item_grids: ${tests.length} tests passed`);
})().catch((error) => {
	console.error(error);
	process.exitCode = 1;
});
