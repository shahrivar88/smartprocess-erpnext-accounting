const spSettlementWorkbench = {
	API: "smartprocess_erpnext_accounting.smartprocess_accounting.settlement.workbench",
	ROUTE: "settlement-workbench",

	method(name) {
		return `${this.API}.${name}`;
	},

	filtersOf(page) {
		return {
			company: page.company.get_value(),
			party_type: page.party_type.get_value(),
			party: page.party.get_value(),
			account: page.account.get_value(),
			currency: page.currency.get_value(),
		};
	},

	filtersReady(filters) {
		return Boolean(filters.company && filters.party_type && filters.party && filters.account);
	},

	allocationDisplayRows(rows) {
		return (rows || [])
			.filter((row) => Number(row.allocated_amount || 0))
			.map((row) => ({
				payment: row.reference_name || "",
				invoice: row.invoice_number || "",
				amount: Number(row.allocated_amount || 0),
				currency: row.currency || "",
			}));
	},

	allocationTotals(rows) {
		const display = this.allocationDisplayRows(rows);
		const by_currency = {};
		for (const row of display) {
			by_currency[row.currency] = (by_currency[row.currency] || 0) + row.amount;
		}
		return { count: display.length, by_currency };
	},

	allocationRows(invoices, payments) {
		const rows = [];
		const openInvoices = invoices.map((row) => ({ ...row }));
		const openPayments = payments.map((row) => ({ ...row }));
		for (const payment of openPayments) {
			let left = Number(payment.amount || 0);
			for (const invoice of openInvoices) {
				const outstanding = Number(invoice.outstanding_amount || 0);
				if (left <= 0 || outstanding <= 0) {
					continue;
				}
				const allocated = Math.min(left, outstanding);
				rows.push({
					reference_type: payment.reference_type,
					reference_name: payment.reference_name,
					invoice_type: invoice.invoice_type,
					invoice_number: invoice.invoice_number,
					allocated_amount: allocated,
					amount: Number(payment.amount || 0),
					unreconciled_amount: Number(payment.amount || 0),
					currency: invoice.currency,
				});
				left -= allocated;
				invoice.outstanding_amount = outstanding - allocated;
			}
		}
		return rows;
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = spSettlementWorkbench;
}
