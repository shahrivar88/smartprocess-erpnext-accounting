const assert = require("node:assert/strict");
const {
	STAGE,
	rowStageIssue,
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

function issueAt(stage, row) {
	return rowStageIssue(stage, row, RECIPIENT_TYPES, COMPANY_CURRENCY);
}

// A. A row the user has not started (stage 0) never validates — defaults like
// amount=0 / rate=0 do not count as user entry, and neither does the Add Row
// copy of a previous row.
{
	const untouched = issueAt(0, freshRow());
	assert.equal(untouched, null);

	const copied = freshRow();
	copied.receipt_currency = "USD";
	copied.receipt_recipient_type = "Customer";
	copied.receipt_recipient = "CUST-A";
	copied.credit_account = "1020-USD";
	copied.credit_exchange_rate = 1500000;
	assert.equal(issueAt(0, copied), null, "Add Row copy at stage 0 must not validate");
}

// B. Choosing Currency (stage 1) validates the currency alone — no amount,
// account or rate errors yet.
{
	const row = freshRow();
	row.receipt_currency = "USD";
	assert.equal(issueAt(STAGE.CURRENCY, row), null);

	assert.deepEqual(
		issueAt(STAGE.CURRENCY, freshRow()),
		["receipt_currency", "ارز ردیف الزامی است."],
		"clearing/reaching stage 1 without a currency reports only the currency",
	);
}

// C. Choosing Type (stage 2) validates currency and type only — future fields
// (معین, amount, rate) are not touched.
{
	const row = freshRow();
	row.receipt_currency = "USD";
	row.receipt_recipient_type = "Customer";
	assert.equal(issueAt(STAGE.TYPE, row), null);

	row.receipt_recipient_type = "";
	assert.deepEqual(
		issueAt(STAGE.TYPE, row),
		["receipt_recipient_type", "نوع پرداخت‌کننده را انتخاب کنید."],
		"missing type reports the type, nothing else",
	);
}

// D. Choosing the Entity (stage 3) requires Party/Bank Account but never the
// Account-type entity, and still no amount check.
{
	const base = freshRow();
	base.receipt_currency = "USD";
	base.receipt_recipient_type = "Customer";

	const party = { ...base, receipt_recipient: "CUST-A" };
	assert.equal(issueAt(STAGE.ENTITY, party), null);
	assert.deepEqual(issueAt(STAGE.ENTITY, base), [
		"receipt_recipient",
		"پرداخت‌کننده الزامی است.",
	]);

	const bank = { ...freshRow(), receipt_currency: "USD", receipt_recipient_type: "Bank Account" };
	assert.deepEqual(issueAt(STAGE.ENTITY, bank), [
		"receipt_recipient",
		"حساب بانکی الزامی است.",
	]);

	const accountType = { ...freshRow(), receipt_currency: "USD", receipt_recipient_type: "Account" };
	assert.equal(
		issueAt(STAGE.ENTITY, accountType),
		null,
		"Account-type rows have no entity field: server parity",
	);
}

// The معین stage (4) requires the account, after which Amount (5) must be
// positive; the foreign Rate (6) must be positive, and a base-currency row
// never needs a rate.
{
	const base = freshRow();
	base.receipt_currency = "USD";
	base.receipt_recipient_type = "Customer";
	base.receipt_recipient = "CUST-A";

	assert.deepEqual(issueAt(STAGE.ACCOUNT, base), [
		"credit_account",
		"معین پرداخت‌کننده الزامی است.",
	]);

	const withAccount = { ...base, credit_account: "1020-USD" };
	assert.equal(issueAt(STAGE.ACCOUNT, withAccount), null);
	assert.deepEqual(issueAt(STAGE.AMOUNT, withAccount), [
		"credit_amount",
		"مبلغ باید بزرگ‌تر از صفر باشد.",
	], "amount=0 errors only once the user reached the Amount stage");

	const withAmount = { ...withAccount, credit_amount: 100 };
	assert.equal(issueAt(STAGE.AMOUNT, withAmount), null);
	assert.deepEqual(issueAt(STAGE.RATE, withAmount), [
		"credit_exchange_rate",
		"نرخ باید بزرگ‌تر از صفر باشد.",
	], "foreign row with rate=0 errors at the Rate stage");

	const withRate = { ...withAmount, credit_exchange_rate: 1500000 };
	assert.equal(issueAt(STAGE.RATE, withRate), null);

	const baseCurrency = { ...withAmount, receipt_currency: COMPANY_CURRENCY, credit_exchange_rate: 0 };
	assert.equal(
		issueAt(STAGE.RATE, baseCurrency),
		null,
		"base-currency rows never require a rate",
	);
}

// F. The first relevant problem wins (server order mirrored), so a later stage
// never masks an earlier one.
{
	const broken = freshRow();
	broken.receipt_recipient_type = "Customer";
	broken.receipt_recipient = "CUST-A";
	broken.credit_account = "1020-USD";
	broken.credit_amount = 0;
	broken.credit_exchange_rate = 0;
	assert.deepEqual(issueAt(STAGE.RATE, broken), [
		"receipt_currency",
		"ارز ردیف الزامی است.",
	], "missing currency is reported before the zero amount");
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
