{% include "smartprocess_erpnext_accounting/smartprocess_accounting/doctype/smartprocess_accounting_document/receipt/receipt_numbers.js" %}
{% include "smartprocess_erpnext_accounting/smartprocess_accounting/doctype/smartprocess_receipt_conversion/conversion/conversion_legs.js" %}
{% include "smartprocess_erpnext_accounting/smartprocess_accounting/doctype/smartprocess_receipt_conversion/conversion/conversion_form.js" %}

frappe.ui.form.on("SmartProcess Receipt Conversion", {
	setup(frm) {
		spConversionForm.setup(frm);
	},
	refresh(frm) {
		return spConversionForm.refresh(frm);
	},
	before_submit(frm) {
		spConversionForm.beforeSubmit(frm);
	},
	target_currency(frm) {
		return spConversionForm.currencyChanged(frm);
	},
});

frappe.ui.form.on("SmartProcess Receipt Conversion Leg", {
	fill_remaining(frm, cdt, cdn) {
		return spConversionForm.fillRemaining(frm, cdt, cdn);
	},
	conversion_amount(frm, cdt, cdn) {
		spConversionForm.amountChanged(frm, cdt, cdn);
	},
	target_rate(frm, cdt, cdn) {
		spConversionForm.rateChanged(frm, cdt, cdn);
	},
	target_party_type(frm, cdt, cdn) {
		return spConversionForm.partyTypeChanged(frm, cdt, cdn);
	},
	target_party(frm, cdt, cdn) {
		return spConversionForm.partyChanged(frm, cdt, cdn);
	},
	target_account(frm, cdt, cdn) {
		return spConversionForm.accountChanged(frm, cdt, cdn);
	},
});
