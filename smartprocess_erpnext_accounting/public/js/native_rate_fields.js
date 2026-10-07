// Native ERPNext exchange-rate fields and invoice item grids: the same
// display-only number handling as the SmartProcess forms, and the optional
// "allow_exchange_rate_editing" UI unlock. Field values, precision and every
// server rule stay untouched.
(function (root, factory) {
	const api = factory();
	if (typeof module === "object" && module.exports) {
		module.exports = api;
	}
	if (root?.frappe?.ui?.form?.on) {
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
	// DocType → item table → its row DocType. Static grid cells already go through
	// the wrapped frappe.form.formatters; these entries cover the cell inputs and
	// the expanded row editor, which render through format_for_input().
	const ITEM_GRIDS = {
		"Sales Invoice": { items: "Sales Invoice Item" },
		"Purchase Invoice": { items: "Purchase Invoice Item" },
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

	// Display only: the input text loses insignificant zeros and groups thousands
	// while typing; control.value and the document value stay the raw number.
	function prepareInput(control) {
		const numeric = globalThis.smartprocessAccounting?.numeric;
		if (!numeric || typeof control?.format_for_input !== "function" || preparedControls.has(control)) {
			return;
		}
		preparedControls.add(control);
		const settings = flags();
		if (Number(settings.hide_insignificant_trailing_zeros)) {
			const formatForInput = control.format_for_input;
			control.format_for_input = function (value) {
				return numeric.compactFormattedNumber(formatForInput.call(this, value), decimalSeparator());
			};
			if (control.$input && typeof control.set_formatted_input === "function") {
				control.set_formatted_input(typeof control.get_value === "function" ? control.get_value() : control.value);
			}
		}
		numeric.liveNumberSeparator.attach(control, () => settings.live_number_separator || {});
	}

	function prepareRateInputs(frm) {
		for (const fieldname of Object.keys(RATE_FIELDS[frm?.doctype] || {})) {
			prepareInput(frm.fields_dict?.[fieldname]);
		}
	}

	function prepareItemControl(control) {
		const df = control?.df;
		if (df && ITEM_NUMERIC_FIELDS.has(df.fieldname) && NUMERIC_FIELDTYPES.has(df.fieldtype)) {
			prepareInput(control);
		}
	}

	// Frappe builds a row's cell controls lazily, when the row becomes editable.
	// The make_control of this one GridRow instance is wrapped once, so each cell
	// control is prepared as soon as it is built; the GridRow class is untouched.
	function prepareGridRow(gridRow) {
		const grid = gridRow?.grid;
		if (!ITEM_GRIDS[grid?.frm?.doctype]?.[grid?.df?.fieldname]) {
			return;
		}
		if (!preparedRows.has(gridRow) && typeof gridRow.make_control === "function") {
			preparedRows.add(gridRow);
			const makeControl = gridRow.make_control;
			gridRow.make_control = function (column, ...rest) {
				const result = makeControl.call(this, column, ...rest);
				prepareItemControl(column?.field);
				return result;
			};
		}
		for (const control of gridRow.on_grid_fields || []) {
			prepareItemControl(control);
		}
		for (const control of Object.values(gridRow.grid_form?.fields_dict || {})) {
			prepareItemControl(control);
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

	// Every doctype_js copy of this file runs this; each DocType is registered once.
	function register(frappe) {
		const app = (globalThis.smartprocessAccounting = globalThis.smartprocessAccounting || {});
		const registered = (app.nativeRateDoctypes = app.nativeRateDoctypes || new Set());
		const once = (doctype, events) => {
			if (!registered.has(doctype)) {
				registered.add(doctype);
				frappe.ui.form.on(doctype, events);
			}
		};
		for (const doctype of Object.keys(RATE_FIELDS)) {
			once(doctype, { setup: setupForm, refresh: refreshForm });
		}
		for (const rowDoctypes of Object.values(ITEM_GRIDS)) {
			for (const rowDoctype of Object.values(rowDoctypes)) {
				once(rowDoctype, { form_render: prepareRowForm });
			}
		}
	}

	return {
		RATE_FIELDS,
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
		register,
	};
});
