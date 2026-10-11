// Central default receivable account in a draft Sales Invoice's Debit To.
// The engine is invoice_default_account.js, loaded just before this file.
(function (root) {
	const inNode = typeof module === "object" && module.exports;
	const core = inNode ? require("./invoice_default_account.js") : root.smartprocess_invoice_default_account;
	const api = core.create({
		doctype: "Sales Invoice",
		method: "smartprocess_erpnext_accounting.smartprocess_accounting.sales_invoice_default_account.propose_for_draft",
		partyField: "customer",
		accountField: "debit_to",
		mappedSources: [
			["delivery_note", "Delivery Note"],
			["sales_order", "Sales Order"],
		],
		// The early returns of ERPNext's customer() and company() handlers.
		partyRefills: () => true,
		companyRefills: (doc) => !(doc.__onload?.load_after_mapping && doc.debit_to),
		followAccountRefill: false,
		settle: false,
	});
	if (inNode) {
		module.exports = api;
	}
	if (root?.frappe?.ui?.form?.on) {
		api.register(root.frappe);
	}
})(typeof window !== "undefined" ? window : globalThis);
