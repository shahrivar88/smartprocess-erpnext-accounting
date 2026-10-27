const assert = require("node:assert/strict");
const {
	compactFormattedNumber,
	wrapNumericFormatters,
	liveNumberSeparator,
	trailingZerosEnabledFor,
	liveSeparatorConfigFor,
} = require("../../public/js/smartprocess_numeric.js");

const cases = [
	["100.000000000", ".", "100"],
	["100.500000000", ".", "100.5"],
	["100.120000000", ".", "100.12"],
	["0.000001000", ".", "0.000001"],
	["1,000,000.500000000000", ".", "1,000,000.5"],
	["1.000.000,500000000000", ",", "1.000.000,5"],
	[
		'<span class="currency">B 100.000000000</span>',
		".",
		'<span class="currency">B 100</span>',
	],
	["100.00", ".", "100"],
	["100.50", ".", "100.5"],
	["100.05", ".", "100.05"],
	["0.00", ".", "0"],
	["-20.00", ".", "-20"],
	["1.230000", ".", "1.23"],
	["1,500,000.000000", ".", "1,500,000"],
	["1,500,000", ".", "1,500,000"],
	["1.500.000", ",", "1.500.000"],
	["-1.234,50", ",", "-1.234,5"],
	["$ 1,250.50", ".", "$ 1,250.5"],
	["1,250.00 IRR", ".", "1,250 IRR"],
	["Rs. 1,250.00", ".", "Rs. 1,250"],
	["100.00 د.إ", ".", "100 د.إ"],
	["12.50%", ".", "12.5%"],
	["1 234,000", ",", "1 234"],
	["<div style='text-align: right'>100.00</div>", ".", "<div style='text-align: right'>100</div>"],
	["100.00", "", "100.00"],
	["", ".", ""],
];

for (const [input, separator, expected] of cases) {
	const storedValue = input;
	assert.equal(compactFormattedNumber(input, separator), expected);
	assert.equal(input, storedValue, "formatting must not mutate the source value");
}

console.log(`smartprocess_numeric: ${cases.length} cases passed`);

// Global formatter registry wrap: display string only, original args untouched.
{
	const calls = [];
	const formatters = {
		Currency: (value, df, options) => (options?.only_value ? `${value}.00` : `<div>${value}.00</div>`),
		Float: (value, df) => (df.options ? formatters.Currency(value, df) : `${value}.230000`),
		Percent: (value) => `${value}.50%`,
		Int: (value) => `${value}.00`,
		Data: (value) => `${value}.00`,
	};
	const decimalFor = (fieldtype) => {
		calls.push(fieldtype);
		return ".";
	};
	assert.equal(wrapNumericFormatters(formatters, decimalFor), true);
	assert.equal(wrapNumericFormatters(formatters, decimalFor), false, "installs once");
	const df = { fieldtype: "Currency" };
	assert.equal(formatters.Currency(100, df), "<div>100</div>");
	assert.equal(formatters.Currency(100, df, { only_value: true }), "100");
	assert.equal(formatters.Float(1, { fieldtype: "Float" }), "1.23");
	assert.equal(formatters.Float(7, { fieldtype: "Float", options: "currency" }), "<div>7</div>");
	assert.equal(formatters.Float(1, { fieldtype: "Float" }, { always_show_decimals: 1 }), "1.23");
	assert.equal(formatters.Percent(12, { fieldtype: "Percent" }), "12.5%");
	assert.equal(formatters.Int(5, {}), "5.00", "Int is not wrapped");
	assert.equal(formatters.Data(5, {}), "5.00", "non-numeric types are not wrapped");
	assert.deepEqual(df, { fieldtype: "Currency" }, "docfield is not mutated");
	assert.ok(!calls.includes("Int"));
	console.log("wrapNumericFormatters: 10 cases passed");
}

{
	const formatters = {
		Currency: (value) => `${value}.00`,
	};
	wrapNumericFormatters(
		formatters,
		() => ".",
		(doctype, parenttype) => doctype === "Sales Invoice" || parenttype === "Sales Invoice",
	);
	assert.equal(formatters.Currency(100, { fieldtype: "Currency" }, {}, { doctype: "Sales Invoice" }), "100");
	assert.equal(
		formatters.Currency(100, { fieldtype: "Currency" }, {}, { doctype: "Journal Entry" }),
		"100.00",
		"disabled DocTypes keep the native formatter",
	);
	assert.equal(
		formatters.Currency(12, { fieldtype: "Currency", parent: "Sales Invoice Item" }, {}, {
			doctype: "Sales Invoice Item",
			parenttype: "Sales Invoice",
		}),
		"12",
		"child rows follow the parent DocType",
	);
	globalThis.frappe = {
		boot: {
			smartprocess_accounting: {
				hide_insignificant_trailing_zeros: 1,
				live_number_separator: { enabled: 1, separator: ",", decimal_str: ".", group_str: "," },
				hide_trailing_zeros_doctypes: { "Sales Invoice": 1, Quotation: 0 },
				live_separator_doctypes: { "Sales Invoice": 1, Quotation: 0 },
			},
		},
	};
	assert.equal(trailingZerosEnabledFor("Sales Invoice"), true);
	assert.equal(trailingZerosEnabledFor("Quotation"), false);
	assert.equal(trailingZerosEnabledFor("Sales Invoice Item", "Sales Invoice"), true);
	assert.equal(liveSeparatorConfigFor("Quotation").enabled, false);
	assert.equal(liveSeparatorConfigFor("Sales Invoice").enabled, true);
	console.log("doctype-gated formatters: 7 cases passed");
}

// Live thousands separator — pure formatting/cleaning/caret functions.
const liveCases = [
	["1234567", ",", "1,234,567"],
	["1234567", "٬", "1٬234٬567"],
	["1234567", " ", "1 234 567"],
	["1500000.25", ",", "1,500,000.25"],
	["-1234", ",", "-1,234"],
	["1.5", ",", "1.5"],
	["12+3", ",", "12+3"], // math expression input stays untouched
	["", ",", ""],
];
for (const [input, separator, expected] of liveCases) {
	const config = { enabled: 1, separator, decimal_str: ".", group_str: "," };
	assert.equal(liveNumberSeparator.formatLiveNumberText(input, config), expected);
}
const siteConfig = { decimal_str: ".", group_str: "," };
assert.equal(liveNumberSeparator.cleanNumericText("1٬234.5", siteConfig), "1234.5");
assert.equal(liveNumberSeparator.cleanNumericText("1,500,000.25", siteConfig), "1500000.25");
assert.equal(liveNumberSeparator.cleanNumericText("1500+50", siteConfig), "1500+50");
assert.equal(liveNumberSeparator.cleanNumericText(1500.5, siteConfig), 1500.5);
assert.equal(liveNumberSeparator.mapCaret("12,", "123,456"), 2);
assert.equal(liveNumberSeparator.mapCaret("1", "1,234"), 1);
assert.equal(liveNumberSeparator.toDisplayNumericText("1234.5", { decimal_str: "," }), "1234,5");
assert.equal(liveNumberSeparator.toDisplayNumericText("1.234.5", { decimal_str: "," }), "1.234,5");
console.log(`live_number_separator: ${liveCases.length + 8} cases passed`);

// Raw/model value vs display text. A Frappe-like Float format (precision 9,
// grouped) is compacted; the display must read back as exactly the raw number.
{
	const frappeFloat = (value, precision = 9) => {
		const [integer, fraction] = Math.abs(value).toFixed(precision).split(".");
		return `${value < 0 ? "-" : ""}${integer.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.${fraction}`;
	};
	const rawCases = [
		["0", "0"],
		["1", "1"],
		["1.0", "1"],
		["1.000000", "1"],
		["1.20", "1.2"],
		["1.200000", "1.2"],
		["1.02", "1.02"],
		["1000", "1,000"],
		["1000.00", "1,000"],
		["1000.50", "1,000.5"],
		["1000.05", "1,000.05"],
		["100.05", "100.05"],
		["15000.000000", "15,000"],
		["15000.500000000", "15,000.5"],
		["15000.050000000", "15,000.05"],
		["1500000.5", "1,500,000.5"],
		["-1500000.5", "-1,500,000.5"],
		["0.000001", "0.000001"],
		["987654321012.25", "987,654,321,012.25"],
	];
	const site = { decimal_str: ".", group_str: "," };
	for (const [stored, expected] of rawCases) {
		const raw = Number(stored);
		const display = compactFormattedNumber(frappeFloat(raw), ".");
		assert.equal(display, expected, stored);
		assert.equal(Number(liveNumberSeparator.cleanNumericText(display, site)), raw, `${stored} reads back unchanged`);
		assert.equal(raw, Number(stored), "the raw value is never touched");
	}
	// Persian/RTL context: the wrapper text and a "," decimal site format.
	assert.equal(
		compactFormattedNumber('<span dir="rtl">ریال 15,000.000000000</span>', "."),
		'<span dir="rtl">ریال 15,000</span>',
	);
	assert.equal(compactFormattedNumber("1.500.000,500000000", ","), "1.500.000,5");
	assert.equal(compactFormattedNumber("100,050000", ","), "100,05");
	console.log(`raw_vs_display: ${rawCases.length + 3} cases passed`);
}

// Live separator on a control: display text changes, the parsed value stays raw.
{
	const makeControl = () => {
		const listeners = [];
		const element = {
			value: "",
			selectionStart: null,
			addEventListener: (type, handler) => listeners.push([type, handler]),
			setSelectionRange() {},
		};
		const control = { $input: { get: () => element }, parse: (value) => (value === "" ? null : parseFloat(value)) };
		const type = (text) => {
			element.value = text;
			element.selectionStart = text.length;
			for (const [, handler] of listeners) handler();
		};
		return { control, element, listeners, type };
	};
	const on = { enabled: 1, separator: ",", decimal_str: ".", group_str: "," };
	const typed = makeControl();
	liveNumberSeparator.attach(typed.control, () => on);
	liveNumberSeparator.attach(typed.control, () => on);
	assert.equal(typed.listeners.length, 1, "attaching twice adds one listener");
	for (const [text, display, raw] of [
		["1500000.5", "1,500,000.5", 1500000.5],
		["-1500000.5", "-1,500,000.5", -1500000.5],
		["1000.05", "1,000.05", 1000.05],
		["0.000001", "0.000001", 0.000001],
	]) {
		typed.type(text);
		assert.equal(typed.element.value, display);
		assert.equal(typed.control.parse(typed.element.value), raw, `${text} parses to the raw number`);
		assert.notEqual(typeof typed.control.parse(typed.element.value), "string", "never a grouped string");
	}
	const persian = makeControl();
	liveNumberSeparator.attach(persian.control, () => ({ ...on, separator: "٬" }));
	persian.type("1500000.5");
	assert.equal(persian.element.value, "1٬500٬000.5");
	assert.equal(persian.control.parse(persian.element.value), 1500000.5);
	const off = makeControl();
	liveNumberSeparator.attach(off.control, () => ({ ...on, enabled: 0 }));
	off.type("1500000.5");
	assert.equal(off.element.value, "1500000.5", "setting off leaves the input text alone");
	assert.equal(off.control.parse("1500000.5"), 1500000.5);
	console.log("live_separator_control: 13 cases passed");
}
