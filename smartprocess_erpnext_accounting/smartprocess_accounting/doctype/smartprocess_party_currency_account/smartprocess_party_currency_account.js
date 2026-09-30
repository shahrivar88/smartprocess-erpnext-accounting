frappe.ui.form.on("SmartProcess Party Currency Account", {
	setup(frm) {
		frm.set_query("party_type", () => ({
			filters: { name: ["in", ["Customer", "Supplier", "Employee", "SmartProcess Financial Intermediary"]] },
		}));
		frm.set_query("account", () => ({
			filters: {
				company: frm.doc.company,
				account_currency: frm.doc.currency,
				disabled: 0,
				is_group: 0,
			},
		}));
	},
});
