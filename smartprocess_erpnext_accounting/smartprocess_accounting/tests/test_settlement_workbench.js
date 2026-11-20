const assert = require("node:assert/strict");
const path = require("node:path");

const workbench = require("../page/settlement_workbench/workbench_logic.js");

function test(name, fn) {
	fn();
	console.log(`ok - ${name}`);
}

test("workbench API stays on the settlement module", () => {
	assert.equal(workbench.method("load_entries"), "smartprocess_erpnext_accounting.smartprocess_accounting.settlement.workbench.load_entries");
	assert.equal(workbench.ROUTE, "settlement-workbench");
});

test("filters are ready only with company party and account", () => {
	assert.equal(workbench.filtersReady({ company: "SP", party_type: "Customer", party: "C", account: "Debtors" }), true);
	assert.equal(workbench.filtersReady({ company: "SP", party_type: "Customer", party: "C" }), false);
});

test("FIFO can allocate one payment across two invoices and leave remainder", () => {
	const rows = workbench.allocationRows(
		[
			{ invoice_type: "Sales Invoice", invoice_number: "SI-1", outstanding_amount: 600, currency: "USD" },
			{ invoice_type: "Sales Invoice", invoice_number: "SI-2", outstanding_amount: 500, currency: "USD" },
		],
		[{ reference_type: "Payment Entry", reference_name: "PE-1", amount: 800 }],
	);
	assert.deepEqual(
		rows.map((row) => [row.invoice_number, row.allocated_amount]),
		[["SI-1", 600], ["SI-2", 200]],
	);
});

test("a payment smaller than the first invoice stays partial", () => {
	const rows = workbench.allocationRows(
		[{ invoice_type: "Sales Invoice", invoice_number: "SI-1", outstanding_amount: 1000, currency: "USD" }],
		[{ reference_type: "Payment Entry", reference_name: "PE-1", amount: 250 }],
	);
	assert.equal(rows.length, 1);
	assert.equal(rows[0].allocated_amount, 250);
});

test("allocation display rows name every financial effect shown in the confirmation", () => {
	const rows = workbench.allocationDisplayRows([
		{ reference_name: "PE-1", invoice_number: "SI-1", allocated_amount: 600, currency: "USD" },
		{ reference_name: "PE-1", invoice_number: "SI-2", allocated_amount: 0, currency: "USD" },
	]);
	assert.deepEqual(rows, [{ payment: "PE-1", invoice: "SI-1", amount: 600, currency: "USD" }]);
});

test("allocation totals group by currency and skip empty allocations", () => {
	const totals = workbench.allocationTotals([
		{ reference_name: "PE-1", invoice_number: "SI-1", allocated_amount: 600, currency: "USD" },
		{ reference_name: "PE-2", invoice_number: "SI-2", allocated_amount: 200, currency: "USD" },
		{ reference_name: "PE-3", invoice_number: "SI-3", allocated_amount: 50, currency: "IRR" },
		{ reference_name: "PE-4", invoice_number: "SI-4", allocated_amount: 0, currency: "IRR" },
	]);
	assert.equal(totals.count, 3);
	assert.deepEqual(totals.by_currency, { USD: 800, IRR: 50 });
});
