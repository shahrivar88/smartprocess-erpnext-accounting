{% include "smartprocess_erpnext_accounting/smartprocess_accounting/party_account/party_profile.js" %}

frappe.ui.form.on("SmartProcess Financial Intermediary", {
	setup(frm) {
		spPartyProfile.setup(frm);
	},
	refresh(frm) {
		return spPartyProfile.refresh(frm);
	},
});
