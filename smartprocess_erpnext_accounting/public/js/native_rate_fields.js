// Native ERPNext exchange-rate fields and invoice item grids: the same
// display-only number handling as the SmartProcess forms, and the optional
// "allow_exchange_rate_editing" UI unlock. Field values, precision and every
// server rule stay untouched.
// Leading semicolon: Frappe concatenates this file into doctype __js after
// other apps' form.on("DocType", { ... }) closings. Without it, ASI turns the
// IIFE into form.on(...)(...), which throws "form.on(...) is not a function".
;(function (root, factory) {
	const api = factory();
	// Node tests export the API. Never write module.exports inside Desk: Frappe
	// evaluates doctype __js with new Function() in global scope, and a leaked
	// `module` would replace the wrong export and break frappe.ui.form.on.
	if (typeof module === "object" && module.exports && !root?.document) {
		module.exports = api;
	}
	if (typeof root?.frappe?.ui?.form?.on === "function") {
		api.register(root.frappe);
	}
})(typeof window !== "undefined" ? window : globalThis, () => {
	// DocType → rate field → the field holding the currency that rate converts.
	// Another DocType is supported by adding one entry here.
	const RATE_FIELDS = {
		"Sales Invoice": { conversion_rate: "currency" },
		"Purchase Invoice": { conversion_rate: "currency" },
		"Payment Entry": {
			source_exchange_rate: "paid_from_account_currency",
			target_exchange_rate: "paid_to_account_currency",
		},
	};
	// Number display only. Exchange-rate unlock stays on RATE_FIELDS.
	const DISPLAY_RATE_FIELDS = {
		...RATE_FIELDS,
		Quotation: { conversion_rate: "currency" },
		"Sales Order": { conversion_rate: "currency" },
		"Purchase Order": { conversion_rate: "currency" },
	};
	// DocType → item table → its row DocType. Static grid cells already go through
	// the wrapped frappe.form.formatters; these entries cover the cell inputs and
	// the expanded row editor, which render through format_for_input().
	const ITEM_GRIDS = {
		"Sales Invoice": { items: "Sales Invoice Item" },
		"Purchase Invoice": { items: "Purchase Invoice Item" },
		Quotation: { items: "Quotation Item" },
		"Sales Order": { items: "Sales Order Item" },
		"Purchase Order": { items: "Purchase Order Item" },
	};
	// A row DocType without one of these fields simply never builds its control.
	const ITEM_NUMERIC_FIELDS = new Set([
		"qty",
		"stock_qty",
		"conversion_factor",
		"rate",
		"price_list_rate",
		"discount_percentage",
		"discount_amount",
		"amount",
		"net_rate",
		"net_amount",
		"base_rate",
		"base_amount",
		"base_net_rate",
		"base_net_amount",
	]);
	const NUMERIC_FIELDTYPES = new Set(["Float", "Currency", "Percent"]);
	const preparedControls = new WeakSet();
	const preparedRows = new WeakSet();
	const watchedForms = new WeakSet();

	function flags() {
		return globalThis.frappe?.boot?.smartprocess_accounting || {};
	}

	function companyCurrency(frm) {
		const erpnext = globalThis.erpnext;
		return frm.doc.company && typeof erpnext?.get_currency === "function" ? erpnext.get_currency(frm.doc.company) : "";
	}

	// Editable only for a Draft the user may write, a field the DocType itself
	// does not make read-only, and a foreign currency (a Company-currency rate is 1).
	function canEditRate(frm, fieldname) {
		const currencyField = RATE_FIELDS[frm?.doctype]?.[fieldname];
		if (!currencyField || !Number(flags().allow_exchange_rate_editing) || frm.doc?.docstatus !== 0) {
			return false;
		}
		const base = globalThis.frappe?.meta?.docfield_map?.[frm.doctype]?.[fieldname];
		if (!base || Number(base.read_only) || !frm.perm?.[base.permlevel || 0]?.write) {
			return false;
		}
		const currency = frm.doc[currencyField];
		const company = companyCurrency(frm);
		return Boolean(currency && company && currency !== company);
	}

	// ERPNext applies its stale-rate lock as set_df_property(rate, "read_only", 1)
	// (a client-only lock; Accounts Settings > Allow Stale Exchange Rates). Only
	// that lock is skipped, on this form instance, for a rate canEditRate() allows.
	function guardRateLock(frm) {
		if (!frm || frm.__sp_rate_lock_guard || typeof frm.set_df_property !== "function") {
			return;
		}
		frm.__sp_rate_lock_guard = true;
		const setDfProperty = frm.set_df_property;
		frm.set_df_property = function (fieldname, property, value, ...rest) {
			const unlocked = property === "read_only" && Number(value) && canEditRate(this, fieldname);
			return setDfProperty.call(this, fieldname, property, unlocked ? 0 : value, ...rest);
		};
	}

	function decimalSeparator() {
		const format = typeof globalThis.get_number_format === "function" ? globalThis.get_number_format() : null;
		const info = format && typeof globalThis.get_number_format_info === "function" ? globalThis.get_number_format_info(format) : null;
		return info?.decimal_str || ".";
	}

	function controlDoctype(control, fallback) {
		return (
			fallback ||
			control?.frm?.doctype ||
			control?.grid?.frm?.doctype ||
			control?.doc?.parenttype ||
			control?.doc?.doctype ||
			control?.df?.parent ||
			""
		);
	}

	// Display only: the input text loses insignificant zeros and groups thousands
	// while typing; control.value and the document value stay the raw number.
	function prepareInput(control, doctype) {
		const numeric = globalThis.smartprocessAccounting?.numeric;
		if (!numeric || typeof control?.format_for_input !== "function" || preparedControls.has(control)) {
			return;
		}
		preparedControls.add(control);
		const parenttype = control?.doc?.parenttype || "";
		const target = controlDoctype(control, doctype);
		const zerosOn = numeric.trailingZerosEnabledFor
			? numeric.trailingZerosEnabledFor(target, parenttype)
			: Number(flags().hide_insignificant_trailing_zeros);
		if (zerosOn) {
			const formatForInput = control.format_for_input;
			control.format_for_input = function (value) {
				return numeric.compactFormattedNumber(formatForInput.call(this, value), decimalSeparator());
			};
			if (control.$input && typeof control.set_formatted_input === "function") {
				control.set_formatted_input(typeof control.get_value === "function" ? control.get_value() : control.value);
			}
		}
		numeric.liveNumberSeparator.attach(control, () =>
			numeric.liveSeparatorConfigFor
				? numeric.liveSeparatorConfigFor(target, parenttype)
				: flags().live_number_separator || {},
		);
	}

	function prepareRateInputs(frm) {
		for (const fieldname of Object.keys(DISPLAY_RATE_FIELDS[frm?.doctype] || {})) {
			prepareInput(frm.fields_dict?.[fieldname], frm.doctype);
		}
	}

	function prepareItemControl(control, doctype) {
		const df = control?.df;
		if (df && ITEM_NUMERIC_FIELDS.has(df.fieldname) && NUMERIC_FIELDTYPES.has(df.fieldtype)) {
			prepareInput(control, doctype);
		}
	}

	// Frappe builds a row's cell controls lazily, when the row becomes editable.
	// The make_control of this one GridRow instance is wrapped once, so each cell
	// control is prepared as soon as it is built; the GridRow class is untouched.
	function prepareGridRow(gridRow) {
		const grid = gridRow?.grid;
		const doctype = grid?.frm?.doctype;
		if (!ITEM_GRIDS[doctype]?.[grid?.df?.fieldname]) {
			return;
		}
		if (!preparedRows.has(gridRow) && typeof gridRow.make_control === "function") {
			preparedRows.add(gridRow);
			const makeControl = gridRow.make_control;
			gridRow.make_control = function (column, ...rest) {
				const result = makeControl.call(this, column, ...rest);
				prepareItemControl(column?.field, doctype);
				return result;
			};
		}
		for (const control of gridRow.on_grid_fields || []) {
			prepareItemControl(control, doctype);
		}
		for (const control of Object.values(gridRow.grid_form?.fields_dict || {})) {
			prepareItemControl(control, doctype);
		}
	}

	// Frappe triggers "grid-row-render" on the form wrapper for every rendered row.
	function watchItemGrids(frm) {
		const $ = globalThis.jQuery;
		if (!ITEM_GRIDS[frm?.doctype] || !frm.wrapper || typeof $ !== "function" || watchedForms.has(frm)) {
			return;
		}
		watchedForms.add(frm);
		$(frm.wrapper).on("grid-row-render", (event, gridRow) => prepareGridRow(gridRow));
	}

	function prepareItemGrids(frm) {
		for (const fieldname of Object.keys(ITEM_GRIDS[frm?.doctype] || {})) {
			for (const gridRow of frm.fields_dict?.[fieldname]?.grid?.grid_rows || []) {
				prepareGridRow(gridRow);
			}
		}
	}

	// "form_render" of the row DocType: the expanded row editor was just built.
	function prepareRowForm(frm, cdt, cdn) {
		const parentfield = globalThis.locals?.[cdt]?.[cdn]?.parentfield;
		prepareGridRow(frm?.fields_dict?.[parentfield]?.grid?.get_row?.(cdn));
	}

	function setupForm(frm) {
		guardRateLock(frm);
		watchItemGrids(frm);
	}

	function refreshForm(frm) {
		prepareRateInputs(frm);
		watchItemGrids(frm);
		prepareItemGrids(frm);
	}

	// Bind the already-open form only after layout has built fields_dict.
	// Calling refresh earlier is a no-op; the refresh handler runs again.
	function bindOpenForm(frm) {
		const open = frm || globalThis.cur_frm;
		if (!open || !DISPLAY_RATE_FIELDS[open.doctype]) {
			return;
		}
		setupForm(open);
		if (open.fields_dict && Object.keys(open.fields_dict).length) {
			refreshForm(open);
		}
	}

	// Every doctype_js copy of this file runs this; each DocType is registered once.
	// A single "*" handler covers the first refresh even if this file is evaluated
	// in the middle of another DocType's concatenated __js bundle.
	function register(frappe) {
		if (typeof frappe?.ui?.form?.on !== "function") {
			return;
		}
		const app = (globalThis.smartprocessAccounting = globalThis.smartprocessAccounting || {});
		const registered = (app.nativeRateDoctypes = app.nativeRateDoctypes || new Set());
		const once = (doctype, events) => {
			if (!registered.has(doctype)) {
				registered.add(doctype);
				frappe.ui.form.on(doctype, events);
			}
		};
		if (!app.nativeRateWildcard) {
			app.nativeRateWildcard = true;
			frappe.ui.form.on("*", {
				setup(frm) {
					if (DISPLAY_RATE_FIELDS[frm?.doctype]) {
						setupForm(frm);
					}
				},
				refresh(frm) {
					if (DISPLAY_RATE_FIELDS[frm?.doctype]) {
						refreshForm(frm);
					}
				},
				form_render(frm, cdt, cdn) {
					if (ITEM_GRIDS[frm?.doctype]) {
						prepareRowForm(frm, cdt, cdn);
					}
				},
			});
		}
		for (const doctype of Object.keys(DISPLAY_RATE_FIELDS)) {
			once(doctype, { setup: setupForm, refresh: refreshForm });
		}
		for (const rowDoctypes of Object.values(ITEM_GRIDS)) {
			for (const rowDoctype of Object.values(rowDoctypes)) {
				once(rowDoctype, { form_render: prepareRowForm });
			}
		}
		bindOpenForm();
	}

	return {
		RATE_FIELDS,
		DISPLAY_RATE_FIELDS,
		ITEM_GRIDS,
		ITEM_NUMERIC_FIELDS,
		canEditRate,
		guardRateLock,
		prepareInput,
		prepareRateInputs,
		prepareGridRow,
		prepareItemGrids,
		prepareRowForm,
		watchItemGrids,
		bindOpenForm,
		register,
	};
});
