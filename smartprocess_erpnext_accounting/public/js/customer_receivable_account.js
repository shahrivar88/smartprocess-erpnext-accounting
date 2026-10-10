// Optional "customer currency receivable account" rule on the Sales Invoice form.
// The server picks the account and re-checks it on every Save and Submit; this
// file only fills debit_to in a Draft after ERPNext has set its own value.
(function (root, factory) {
	const api = factory();
	if (typeof module === "object" && module.exports) {
		module.exports = api;
	}
	if (root?.frappe?.ui?.form?.on) {
		api.register(root.frappe);
	}
})(typeof window !== "undefined" ? window : globalThis, () => {
	const METHOD =
		"smartprocess_erpnext_accounting.smartprocess_accounting.customer_receivable_account.get_customer_receivable_account";

	function enabled() {
		return Boolean(globalThis.frappe?.boot?.smartprocess_accounting?.customer_currency_receivable_account);
	}

	function applies(frm) {
		const doc = frm.doc;
		return enabled() && doc.docstatus === 0 && !doc.is_return && Boolean(doc.customer && doc.company);
	}

	// Form-level handlers run before ERPNext's controller methods, so wait for the
	// controller's own customer/company requests to finish before setting debit_to.
	function schedule(frm) {
		if (!applies(frm)) {
			return;
		}
		const token = (frm._sp_receivable_token || 0) + 1;
		frm._sp_receivable_token = token;
		setTimeout(() => frappe.after_ajax(() => apply(frm, token)), 0);
	}

	async function apply(frm, token) {
		if (token !== frm._sp_receivable_token || !applies(frm)) {
			return;
		}
		const { customer, company } = frm.doc;
		let account;
		try {
			account = (await frappe.call({ method: METHOD, args: { customer, company } }))?.message;
		} catch (e) {
			return; // Frappe has already shown the server's message.
		}
		const stale = token !== frm._sp_receivable_token || frm.doc.customer !== customer || frm.doc.company !== company;
		if (account && !stale && frm.doc.debit_to !== account) {
			await frm.set_value("debit_to", account);
		}
	}

	function refresh(frm) {
		if (frm.is_new() && frm._sp_receivable_docname !== frm.docname) {
			frm._sp_receivable_docname = frm.docname;
			schedule(frm);
		}
	}

	function register(frappe) {
		const app = (globalThis.smartprocessAccounting = globalThis.smartprocessAccounting || {});
		if (app.customerReceivableRegistered) {
			return;
		}
		app.customerReceivableRegistered = true;
		frappe.ui.form.on("Sales Invoice", { refresh, customer: schedule, company: schedule });
	}

	return { METHOD, enabled, applies, schedule, apply, refresh, register };
});
