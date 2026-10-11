// Narrows the Account picker of a default account row. The server validates the final row.
const SP_DEFAULT_ACCOUNT_TYPES = { Receivable: "Receivable", Payable: "Payable", Bank: "Bank", Cash: "Cash" };
// Purpose labels are translated with this context so the global "Receivable"/"Payable" labels stay untouched.
const SP_DEFAULT_ACCOUNT_ROW = "SmartProcess Default Account";

function spPurposeLabel(value) {
	return value ? frappe.utils.escape_html(__(value, null, SP_DEFAULT_ACCOUNT_ROW)) : "";
}

function spDefaultAccountFilters(row, companyCurrency) {
	const filters = { is_group: 0, disabled: 0 };
	if (row.company) {
		filters.company = row.company;
	}
	if (row.currency) {
		// ERPNext treats an empty Account Currency as the company currency.
		const mayBeEmpty = !companyCurrency || row.currency === companyCurrency;
		filters.account_currency = mayBeEmpty ? ["in", [row.currency, null]] : row.currency;
	}
	if (SP_DEFAULT_ACCOUNT_TYPES[row.account_purpose]) {
		filters.account_type = SP_DEFAULT_ACCOUNT_TYPES[row.account_purpose];
	}
	return filters;
}

// Invoice forms read this flag from boot, which loads once per page; a save must reach this tab too.
function spSyncBootFlags(doc, boot) {
	const flags = boot && boot.smartprocess_accounting;
	if (flags) {
		flags.central_default_accounts = Number(doc.enable_central_default_accounts) ? 1 : 0;
	}
}

if (typeof frappe !== "undefined") {
	frappe.ui.form.on("SmartProcess Accounting Settings", {
		setup(frm) {
			// The table is absent until the site migrates; set_query would throw without it.
			if (!frm.fields_dict.default_accounts) {
				return;
			}
			frm.set_query("account", "default_accounts", (doc, cdt, cdn) => {
				const row = locals[cdt][cdn];
				const company = row.company && frappe.get_doc(":Company", row.company);
				return { filters: spDefaultAccountFilters(row, company && company.default_currency) };
			});
			// The Select control already uses the row DocType as context; the static grid cell does not.
			frappe.meta.docfield_map[SP_DEFAULT_ACCOUNT_ROW].account_purpose.formatter = spPurposeLabel;
			// The grid is already built here and renders its description only once, so fill its slot directly.
			const grid = frm.fields_dict.default_accounts.grid;
			grid.df.description = __("The account of related return invoices is taken from the original invoice.");
			grid.set_grid_description();
			$(grid.parent).find(".grid-description").show();
		},
		after_save(frm) {
			spSyncBootFlags(frm.doc, frappe.boot);
		},
	});
}

if (typeof module === "object" && module.exports) {
	module.exports = { spDefaultAccountFilters, spSyncBootFlags };
}
