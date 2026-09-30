frappe.ui.form.on("SmartProcess Accounting Document", {
	setup(frm) {
		for (const side of ["debit", "credit"]) {
			frm.set_query(`${side}_account`, "operational_pairs", (doc, cdt, cdn) => {
				const row = locals[cdt][cdn];
				const filters = { company: frm.doc.company, disabled: 0, is_group: 0 };
				const category = row[`${side}_account_category`];
				if (["Bank", "Cash", "Receivable", "Payable"].includes(category)) {
					filters.account_type = category;
				} else if (["Expense", "Income"].includes(category)) {
					filters.root_type = category;
				} else if (category === "Financial Intermediary") {
					filters.account_type = "Receivable";
				}
				return { filters };
			});
			frm.set_query(`${side}_party_type`, "operational_pairs", () => ({
				filters: { name: ["in", ["Customer", "Supplier", "Employee", "SmartProcess Financial Intermediary"]] },
			}));
		}
	},
	company(frm) {
		if (!frm.doc.company) {
			return frm.set_value("company_currency", "");
		}
		return frappe.call({
			method: "smartprocess_erpnext_accounting.smartprocess_accounting.v2_api.get_company_currency",
			args: { company: frm.doc.company },
			callback: ({ message }) => {
				frm.set_value("company_currency", message || "");
				for (const row of frm.doc.operational_pairs || []) {
					frappe.model.set_value(row.doctype, row.name, "company_currency", message || "");
				}
			},
		});
	},
});

const spAccountingPair = {
	async refresh_account(frm, cdt, cdn, side) {
		const row = locals[cdt][cdn];
		const account = row[`${side}_account`];
		if (!account || !frm.doc.company) {
			return;
		}
		const { message } = await frappe.call({
			method: "smartprocess_erpnext_accounting.smartprocess_accounting.v2_api.get_account_details",
			args: { account, company: frm.doc.company },
		});
		await frappe.model.set_value(cdt, cdn, `${side}_account_currency`, message.account_currency);
		await frappe.model.set_value(cdt, cdn, "company_currency", frm.doc.company_currency);
		if (message.account_currency === frm.doc.company_currency) {
			await frappe.model.set_value(cdt, cdn, `${side}_exchange_rate`, 1);
		}
		await this.calculate(frm, cdt, cdn, side);
		await this.suggest(frm, cdt, cdn, side);
	},
	async calculate(frm, cdt, cdn, side) {
		const row = locals[cdt][cdn];
		if (row.__sp_calculating) {
			return;
		}
		row.__sp_calculating = true;
		try {
			const accountCurrency = row[`${side}_account_currency`];
			let rate = Number(row[`${side}_exchange_rate`] || 0);
			if (accountCurrency && accountCurrency === frm.doc.company_currency) {
				rate = 1;
				await frappe.model.set_value(cdt, cdn, `${side}_exchange_rate`, 1);
			}
			const amount = Number(row[`${side}_amount`] || 0);
			await frappe.model.set_value(cdt, cdn, `${side}_company_amount`, amount * rate);
			const meaning = accountCurrency && frm.doc.company_currency && rate > 0
				? `1 ${accountCurrency} = ${rate} ${frm.doc.company_currency}`
				: "";
			await frappe.model.set_value(cdt, cdn, `${side}_rate_direction`, meaning);
		} finally {
			row.__sp_calculating = false;
		}
	},
	async suggest(frm, cdt, cdn, side) {
		const row = locals[cdt][cdn];
		const partyType = row[`${side}_party_type`];
		const party = row[`${side}_party`];
		const currency = row[`${side}_account_currency`];
		if (!partyType || !party || !frm.doc.company || !currency) {
			return frappe.model.set_value(cdt, cdn, `${side}_suggested_account`, "");
		}
		const { message } = await frappe.call({
			method: "smartprocess_erpnext_accounting.smartprocess_accounting.v2_api.get_party_account_suggestion",
			args: { party_type: partyType, party, company: frm.doc.company, currency },
		});
		return frappe.model.set_value(cdt, cdn, `${side}_suggested_account`, message || "");
	},
};

const events = {};
for (const side of ["debit", "credit"]) {
	events[`${side}_account`] = (frm, cdt, cdn) => spAccountingPair.refresh_account(frm, cdt, cdn, side);
	events[`${side}_amount`] = (frm, cdt, cdn) => spAccountingPair.calculate(frm, cdt, cdn, side);
	events[`${side}_exchange_rate`] = (frm, cdt, cdn) => spAccountingPair.calculate(frm, cdt, cdn, side);
	events[`${side}_party_type`] = (frm, cdt, cdn) => spAccountingPair.suggest(frm, cdt, cdn, side);
	events[`${side}_party`] = (frm, cdt, cdn) => spAccountingPair.suggest(frm, cdt, cdn, side);
}
frappe.ui.form.on("SmartProcess Accounting Pair", events);
