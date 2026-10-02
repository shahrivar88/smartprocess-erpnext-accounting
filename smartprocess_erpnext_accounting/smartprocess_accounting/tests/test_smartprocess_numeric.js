const assert = require("node:assert/strict");
const { compactFormattedNumber } = require("../../public/js/smartprocess_numeric.js");

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
