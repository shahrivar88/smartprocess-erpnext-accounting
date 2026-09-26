// Copyright (c) 2026, Smart Process and contributors
// For license information, please see license.txt

frappe.ui.form.on("SmartProcess Currency Conversion", {
	setup(frm) {
		frm.set_query("account", "conversion_rows", () => account_query(frm));
		frm.set_query("party_type", "conversion_rows", () => party_type_query());
	},

	onload(frm) {
		frm.$wrapper.addClass("sp-conversion-form");
		load_company_currency(frm, () => {
			ensure_two_rows(frm);
			keep_grid_inline(frm);
		});
	},

	refresh(frm) {
		frm.$wrapper.addClass("sp-conversion-form");
		frm.$wrapper.find(".layout-side-section").hide();
		frm.set_df_property("conversion_rows", "label", "");
		frm.set_df_property("total_debit", "label", "جمع بدهکار");
		frm.set_df_property("total_credit", "label", "جمع بستانکار");
		load_company_currency(frm, () => {
			ensure_two_rows(frm);
			keep_grid_inline(frm);
			refresh_row_currency_state(frm);
			recalculate(frm);
		});
	},

	company(frm) {
		(frm.doc.conversion_rows || []).forEach((row) => {
			frappe.model.set_value(row.doctype, row.name, "account", "");
			frappe.model.set_value(row.doctype, row.name, "account_currency", "");
			frappe.model.set_value(row.doctype, row.name, "party_type", "");
			frappe.model.set_value(row.doctype, row.name, "party", "");
		});
		load_company_currency(frm, () => {
			refresh_row_currency_state(frm);
			recalculate(frm);
		});
	},

	validate(frm) {
		ensure_two_rows(frm);
		recalculate(frm);
	},
});

frappe.ui.form.on("SmartProcess Conversion Row", {
	account(frm, cdt, cdn) {
		apply_account_currency(frm, cdt, cdn);
	},
	account_currency(frm, cdt, cdn) {
		apply_rate_state(frm, cdt, cdn);
		recalculate_row(frm, cdt, cdn);
		recalculate(frm);
	},
	amount(frm, cdt, cdn) {
		recalculate_row(frm, cdt, cdn);
		recalculate(frm);
	},
	exchange_rate(frm, cdt, cdn) {
		recalculate_row(frm, cdt, cdn);
		recalculate(frm);
	},
	party_type(frm, cdt, cdn) {
		const row = frappe.get_doc(cdt, cdn);
		if (!row.party_type) {
			frappe.model.set_value(cdt, cdn, "party", "");
		}
	},
});

function account_query(frm) {
	return {
		filters: {
			company: frm.doc.company,
			is_group: 0,
			disabled: 0,
		},
	};
}

function party_type_query() {
	return {
		filters: {},
	};
}

function extract_value(res, fieldname) {
	if (!res) {
		return "";
	}
	if (typeof res === "string") {
		return res;
	}
	if (res[fieldname]) {
		return res[fieldname];
	}
	if (res.message && res.message[fieldname]) {
		return res.message[fieldname];
	}
	return "";
}

function company_currency_of(frm) {
	return frm._company_currency || "";
}

function is_foreign_row(frm, row) {
	const company_currency = company_currency_of(frm);
	return !!(row.account_currency && company_currency && row.account_currency !== company_currency);
}

function load_company_currency(frm, callback) {
	if (!frm.doc.company) {
		callback && callback("");
		return;
	}
	frappe.db.get_value("Company", frm.doc.company, "default_currency", (res) => {
		const currency = extract_value(res, "default_currency");
		frm._company_currency = currency;
		callback && callback(currency);
	});
}

function keep_grid_inline(frm) {
	const field = frm.get_field("conversion_rows");
	if (!field || !field.grid) {
		return;
	}
	const grid = field.grid;
	grid.cannot_add_rows = true;
	grid.cannot_delete_rows = true;
	frm.set_df_property("conversion_rows", "cannot_add_rows", 1);
	frm.set_df_property("conversion_rows", "cannot_delete_rows", 1);
	grid.sortable_status = false;
	if (grid.grid_sortable && typeof grid.grid_sortable.option === "function") {
		grid.grid_sortable.option("disabled", true);
	}
	(frm.doc.conversion_rows || []).forEach((row) => {
		row._sortable = false;
	});
	if (grid.wrapper) {
		grid.wrapper.addClass("sp-conversion-grid");
		grid.wrapper
			.find(
				".grid-add-row, .grid-remove-rows, .grid-remove-all-rows, .grid-duplicate-row, .btn-open-row, .grid-insert-row, .grid-insert-row-below, .grid-append-row, .grid-duplicate-row"
			)
			.hide();
		grid.wrapper.find(".sortable-handle, .row-check, .grid-row-check").hide();
		grid.wrapper.find(".grid-heading-row .grid-static-col, .grid-heading-row .static-area").css({
			"text-align": "center",
			"justify-content": "center",
		});
	}
	(grid.grid_rows || []).forEach((grid_row) => {
		if (grid_row._inline_only) {
			return;
		}
		grid_row._inline_only = true;
		grid_row.toggle_view = function () {
			if (typeof this.toggle_editable_row === "function") {
				this.toggle_editable_row(true);
			}
			return this;
		};
	});
}

function ensure_two_rows(frm) {
	frm.doc.conversion_rows = frm.doc.conversion_rows || [];
	let changed = false;
	while (frm.doc.conversion_rows.length < 2) {
		const idx = frm.doc.conversion_rows.length + 1;
		frm.add_child("conversion_rows", {
			nature: idx === 1 ? "بدهکار" : "بستانکار",
			exchange_rate: 1,
		});
		changed = true;
	}
	if (frm.doc.conversion_rows.length > 2) {
		frm.doc.conversion_rows = frm.doc.conversion_rows.slice(0, 2);
		changed = true;
	}
	(frm.doc.conversion_rows || []).forEach((row, index) => {
		row.idx = index + 1;
		row.nature = index === 0 ? "بدهکار" : "بستانکار";
		if (!row.account) {
			row.account_currency = "";
		}
	});
	if (changed) {
		frm.refresh_field("conversion_rows");
	}
	keep_grid_inline(frm);
}

function apply_account_currency(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	if (!row.account) {
		frappe.model.set_value(cdt, cdn, "account_currency", "");
		return;
	}
	const requests = [frappe.db.get_value("Account", row.account, "account_currency")];
	if (frm.doc.company) {
		requests.push(frappe.db.get_value("Company", frm.doc.company, "default_currency"));
	}
	Promise.all(requests).then((results) => {
		const account_currency = extract_value(results[0], "account_currency");
		const company_currency = results[1]
			? extract_value(results[1], "default_currency")
			: company_currency_of(frm);
		frm._company_currency = company_currency;
		frappe.model.set_value(cdt, cdn, "account_currency", account_currency);
		apply_rate_state(frm, cdt, cdn);
		const grid = frm.get_field("conversion_rows") && frm.get_field("conversion_rows").grid;
		const grid_row = grid && grid.grid_rows_by_docname && grid.grid_rows_by_docname[cdn];
		if (grid_row) {
			grid_row.refresh_field("account_currency");
			grid_row.refresh_field("exchange_rate");
		}
		recalculate_row(frm, cdt, cdn);
		recalculate(frm);
		keep_grid_inline(frm);
	});
}

function apply_rate_state(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	const foreign = is_foreign_row(frm, row);
	if (!foreign && flt(row.exchange_rate) !== 1) {
		frappe.model.set_value(cdt, cdn, "exchange_rate", 1);
	}
	toggle_row_rate(frm, cdn, foreign);
}

function refresh_row_currency_state(frm) {
	(frm.doc.conversion_rows || []).forEach((row) => {
		if (row.account && !row.account_currency) {
			apply_account_currency(frm, row.doctype, row.name);
			return;
		}
		apply_rate_state(frm, row.doctype, row.name);
		recalculate_row(frm, row.doctype, row.name);
	});
}

function toggle_row_rate(frm, cdn, is_foreign) {
	const grid = frm.get_field("conversion_rows") && frm.get_field("conversion_rows").grid;
	if (!grid || !grid.grid_rows_by_docname) {
		return;
	}
	const grid_row = grid.grid_rows_by_docname[cdn];
	if (grid_row && typeof grid_row.toggle_editable === "function") {
		grid_row.toggle_editable("exchange_rate", !!is_foreign);
	}
}

function recalculate_row(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	const precision = amount_precision(frm);
	const foreign = is_foreign_row(frm, row);
	const amount = finite_number(row.amount);
	const rate = foreign ? finite_number(row.exchange_rate) : 1;
	const base = flt(foreign ? amount * rate : amount, precision);
	if (flt(row.base_amount) !== base) {
		frappe.model.set_value(cdt, cdn, "base_amount", base);
	}
}

function recalculate(frm) {
	const precision = amount_precision(frm);
	const rows = (frm.doc.conversion_rows || []).slice(0, 2);
	const debit = rows[0] ? finite_number(rows[0].base_amount) : 0;
	const credit = rows[1] ? finite_number(rows[1].base_amount) : 0;
	frm.set_value("total_debit", flt(debit, precision));
	frm.set_value("total_credit", flt(credit, precision));
	frm.set_value("difference", flt(debit - credit, precision));
}

function amount_precision(frm) {
	return frm.get_field("total_debit")?.df?.precision || 2;
}

function finite_number(value) {
	const number = flt(value);
	return Number.isFinite(number) ? number : 0;
}
