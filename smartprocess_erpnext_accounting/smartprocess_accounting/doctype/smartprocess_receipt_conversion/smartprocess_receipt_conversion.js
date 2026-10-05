{% include "smartprocess_erpnext_accounting/smartprocess_accounting/doctype/smartprocess_accounting_document/receipt/receipt_numbers.js" %}
{% include "smartprocess_erpnext_accounting/smartprocess_accounting/doctype/smartprocess_receipt_conversion/conversion/conversion_legs.js" %}
{% include "smartprocess_erpnext_accounting/smartprocess_accounting/doctype/smartprocess_receipt_conversion/conversion/conversion_form.js" %}
{% include "smartprocess_erpnext_accounting/smartprocess_accounting/doctype/smartprocess_receipt_conversion/conversion/balance_form.js" %}

frappe.ui.form.on("SmartProcess Receipt Conversion", {
	setup(frm) {
		spConversionForm.setup(frm);
		spBalanceForm.setup(frm);
	},
	async refresh(frm) {
		await spConversionForm.refresh(frm);
		return spBalanceForm.refresh(frm);
	},
	before_submit(frm) {
		if (!spBalanceForm.isBalance(frm)) {
			spConversionForm.beforeSubmit(frm);
		}
	},
	target_currency(frm) {
		if (spBalanceForm.isBalance(frm)) {
			return spBalanceForm.currencyChanged(frm);
		}
		return spConversionForm.currencyChanged(frm);
	},
	conversion_mode(frm) {
		return spBalanceForm.modeChanged(frm);
	},
	company(frm) {
		spBalanceForm.scheduleSummary(frm);
	},
	posting_date(frm) {
		spBalanceForm.scheduleSummary(frm);
	},
	source_party_type(frm) {
		return spBalanceForm.sourcePartyTypeChanged(frm);
	},
	source_party(frm) {
		return spBalanceForm.sourcePartyChanged(frm);
	},
	source_account(frm) {
		spBalanceForm.scheduleSummary(frm);
	},
	conversion_amount(frm) {
		spBalanceForm.schedulePreview(frm);
	},
	target_rate(frm) {
		spBalanceForm.schedulePreview(frm);
	},
	fill_max_convertible(frm) {
		return spBalanceForm.fillMax(frm);
	},
	target_party_type(frm) {
		return spBalanceForm.targetPartyTypeChanged(frm);
	},
	target_party(frm) {
		return spBalanceForm.targetPartyChanged(frm);
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
