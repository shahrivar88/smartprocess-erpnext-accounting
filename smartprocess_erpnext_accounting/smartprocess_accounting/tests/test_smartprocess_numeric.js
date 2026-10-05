const assert = require("node:assert/strict");
const {
	compactFormattedNumber,
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
];

for (const [input, separator, expected] of cases) {
	const storedValue = input;
	assert.equal(compactFormattedNumber(input, separator), expected);
	assert.equal(input, storedValue, "formatting must not mutate the source value");
}

console.log(`smartprocess_numeric: ${cases.length} cases passed`);

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
