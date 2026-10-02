const assert = require("node:assert/strict");
const {
	compactFormattedNumber,
	summarizeReceiptRows,
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

const summary = summarizeReceiptRows(
	[
		{ receipt_currency: "IRR", credit_amount: 50, credit_company_amount: 999 },
		{ receipt_currency: "IRR", credit_amount: 25, credit_company_amount: 999 },
		{ receipt_currency: "USD", credit_amount: 2, credit_company_amount: 300 },
		{ receipt_currency: "USD", credit_amount: 3, credit_company_amount: 600 },
		{ receipt_currency: "EUR", credit_amount: 0, credit_company_amount: 100 },
	],
	"IRR",
);
assert.deepEqual(summary, {
	currencies: [
		{ currency: "IRR", amount: 75, baseAmount: 75, weightedRate: null },
		{ currency: "USD", amount: 5, baseAmount: 900, weightedRate: 180 },
	],
	companyTotal: 975,
});
console.log("receipt_summary: base and weighted foreign totals passed");
