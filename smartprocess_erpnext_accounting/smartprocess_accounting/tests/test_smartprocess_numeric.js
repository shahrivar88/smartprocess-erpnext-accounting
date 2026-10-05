const assert = require("node:assert/strict");
const {
	compactFormattedNumber,
	wrapNumericFormatters,
	liveNumberSeparator,
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
