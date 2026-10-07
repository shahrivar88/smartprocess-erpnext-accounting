// Native ERPNext exchange-rate fields: the same display-only number handling as
// the SmartProcess forms, and the optional "allow_exchange_rate_editing" UI
// unlock. Field values, precision and every server rule stay untouched.
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
	const preparedControls = new WeakSet();

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
				control.set_formatted_input(control.value);
			}
		}
		numeric.liveNumberSeparator.attach(control, () => settings.live_number_separator || {});
	}

	function prepareRateInputs(frm) {
		for (const fieldname of Object.keys(RATE_FIELDS[frm?.doctype] || {})) {
			prepareInput(frm.fields_dict?.[fieldname]);
		}
	}

	// Every doctype_js copy of this file runs this; each DocType is registered once.
	function register(frappe) {
		const app = (globalThis.smartprocessAccounting = globalThis.smartprocessAccounting || {});
		const registered = (app.nativeRateDoctypes = app.nativeRateDoctypes || new Set());
		for (const doctype of Object.keys(RATE_FIELDS)) {
			if (!registered.has(doctype)) {
				registered.add(doctype);
				frappe.ui.form.on(doctype, { setup: guardRateLock, refresh: prepareRateInputs });
			}
		}
	}

	return { RATE_FIELDS, canEditRate, guardRateLock, prepareInput, prepareRateInputs, register };
});
