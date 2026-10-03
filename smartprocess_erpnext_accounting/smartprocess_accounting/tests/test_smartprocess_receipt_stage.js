const assert = require("node:assert/strict");
const {
	rowIssues,
	receiverSummaryCells,
} = require("../../public/js/smartprocess_receipt_stage.js");

const RECIPIENT_TYPES = [
	"Customer",
	"Supplier",
	"Employee",
	"SmartProcess Financial Intermediary",
	"Bank Account",
	"Account",
];
const COMPANY_CURRENCY = "IRR";

const freshRow = () => ({
	receipt_currency: "",
	receipt_recipient_type: "",
	receipt_recipient: "",
	credit_account: "",
	credit_amount: 0,
	credit_exchange_rate: 0,
});

function messages(row, companyCurrency = COMPANY_CURRENCY) {
	return rowIssues(row, RECIPIENT_TYPES, companyCurrency).map(([, message]) => message);
}

// A. An untouched row lists every missing item in report order; the foreign
// Rate rule stays silent while the currency is unknown.
{
	assert.deepEqual(messages(freshRow()), [
		"ارز ردیف الزامی است.",
		"نوع پرداخت‌کننده را انتخاب کنید.",
		"پرداخت‌کننده الزامی است.",
		"معین پرداخت‌کننده الزامی است.",
		"مبلغ باید بزرگ‌تر از صفر باشد.",
	]);
}

// B. The user's example — a foreign Customer row with only currency + type set
// lists all four remaining problems in one message.
{
	const row = freshRow();
	row.receipt_currency = "USD";
	row.receipt_recipient_type = "Customer";
	assert.deepEqual(messages(row), [
		"پرداخت‌کننده الزامی است.",
		"معین پرداخت‌کننده الزامی است.",
		"مبلغ باید بزرگ‌تر از صفر باشد.",
		"نرخ باید بزرگ‌تر از صفر باشد.",
	]);
}

// C. A Bank row without a Bank Account reports the bank-account entity AND the
// ledger account — never only the first of them.
{
	const bank = { ...freshRow(), receipt_currency: "USD", receipt_recipient_type: "Bank Account" };
	assert.deepEqual(messages(bank), [
		"حساب بانکی الزامی است.",
		"معین پرداخت‌کننده الزامی است.",
		"مبلغ باید بزرگ‌تر از صفر باشد.",
		"نرخ باید بزرگ‌تر از صفر باشد.",
	]);
	assert.equal(rowIssues(bank, RECIPIENT_TYPES, COMPANY_CURRENCY)[0][0], "receipt_recipient");
}

// D. Account-type rows have no entity field: the entity rule never fires, and a
// base-currency row never requires a rate.
{
	const accountType = { ...freshRow(), receipt_currency: COMPANY_CURRENCY, receipt_recipient_type: "Account" };
	assert.deepEqual(messages(accountType), [
		"معین پرداخت‌کننده الزامی است.",
		"مبلغ باید بزرگ‌تر از صفر باشد.",
	]);
}

// E. Complete rows report nothing: base currency, foreign with rate, and Bank
// with entity + ledger account.
{
	const base = {
		...freshRow(),
		receipt_currency: COMPANY_CURRENCY,
		receipt_recipient_type: "Customer",
		receipt_recipient: "CUST-A",
		credit_account: "1020",
		credit_amount: 100,
	};
	assert.deepEqual(rowIssues(base, RECIPIENT_TYPES, COMPANY_CURRENCY), []);

	const foreign = { ...base, receipt_currency: "USD", credit_account: "1020-USD", credit_exchange_rate: 1500000 };
	assert.deepEqual(rowIssues(foreign, RECIPIENT_TYPES, COMPANY_CURRENCY), []);

	const bank = {
		...freshRow(),
		receipt_currency: "USD",
		receipt_recipient_type: "Bank Account",
		receipt_recipient: "BANK-ACC-1",
		credit_account: "1020-USD",
		credit_amount: 100,
		credit_exchange_rate: 1500000,
	};
	assert.deepEqual(rowIssues(bank, RECIPIENT_TYPES, COMPANY_CURRENCY), []);
}

// F. Unknown recipient types are invalid; without a company currency context the
// foreign-rate rule never fires.
{
	const badType = { ...freshRow(), receipt_currency: "USD", receipt_recipient_type: "Nope" };
	assert.ok(messages(badType).includes("نوع پرداخت‌کننده را انتخاب کنید."));

	const noCompanyCurrency = {
		...freshRow(),
		receipt_currency: "USD",
		receipt_recipient_type: "Customer",
		receipt_recipient: "CUST-A",
		credit_account: "1020-USD",
		credit_amount: 100,
	};
	assert.deepEqual(rowIssues(noCompanyCurrency, RECIPIENT_TYPES, undefined), []);
}

// Receiver summary cells: aligned 4-column rendering from the canonical message.
const formatValue = (value) => String(value);
{
	// Not ready: every column shows a muted placeholder.
	assert.equal(
		receiverSummaryCells(null, formatValue),
		[
			'<td class="text-muted">—</td>',
			'<td class="text-muted">—</td>',
			'<td class="text-muted">—</td>',
			'<td class="text-muted">—</td>',
		].join(""),
	);

	// The user's example: 240,150,000,000 IRR / 1,500,000 = 160,100 USD.
	const message = {
		currency: "USD",
		amount: "160100.000000000",
		effective_rate: "1500000",
		company_amount: "240150000000.000000000",
	};
	assert.equal(receiverSummaryCells(message, formatValue), [
		"<td>USD</td>",
		"<td>160100</td>",
		"<td>1500000</td>",
		"<td>240150000000</td>",
	].join(""));

	// A missing effective rate renders as a placeholder, never a division.
	const noRate = { ...message, effective_rate: "" };
	assert.equal(receiverSummaryCells(noRate, formatValue), [
		"<td>USD</td>",
		"<td>160100</td>",
		'<td class="text-muted">—</td>',
		"<td>240150000000</td>",
	].join(""));

	// Currency values are HTML-escaped.
	const hostile = { ...message, currency: '<img src=x onerror="alert(1)">' };
	assert.ok(!receiverSummaryCells(hostile, formatValue).includes("<img"));
	assert.ok(receiverSummaryCells(hostile, formatValue).includes("&lt;img"));
}

console.log("smartprocess_receipt_stage: all cases passed");
