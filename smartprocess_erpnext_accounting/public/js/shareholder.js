frappe.ui.form.on("Shareholder", {
	setup(frm) {
		spShareholder.applyCurrencyField(frm);
	},
	refresh(frm) {
		spShareholder.applyCurrencyField(frm);
		if (frm.is_new()) {
			spShareholder.applyCompanyCurrency(frm);
		}
	},
	company(frm) {
		if (frm.is_new()) {
			spShareholder.applyCompanyCurrency(frm);
		}
	},
});

const spShareholder = {
	flags() {
		return frappe.boot?.smartprocess_accounting?.shareholder_accounting || {};
	},

	applyCurrencyField(frm) {
		if (!frm.fields_dict.custom_sp_default_currency) {
			return;
		}
		const flags = this.flags();
		frm.set_df_property("custom_sp_default_currency", "hidden", Number(flags.show_default_currency) ? 0 : 1);
	},

	applyCompanyCurrency(frm) {
		if (!frm.doc.company || frm.doc.custom_sp_default_currency) {
			return;
		}
		if (!Number(this.flags().show_default_currency)) {
			return;
		}
		const company = frappe.get_doc(":Company", frm.doc.company);
		if (company?.default_currency) {
			frm.set_value("custom_sp_default_currency", company.default_currency);
		}
	},
};
