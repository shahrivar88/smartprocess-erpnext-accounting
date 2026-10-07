// Receipt number display: compact decimals (no trailing zeros, when the global
// "Hide Insignificant Trailing Zeros" setting is on) and the live thousands
// separator. Presentation only — model values stay raw numbers.
const SP_RECEIPT_NUMBER_SETTINGS_METHOD =
	"smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_settings.smartprocess_accounting_settings.get_number_input_settings";
const spReceiptCompactControls = new WeakSet();
const spReceiptNumberWrappers = new WeakSet();

const spReceiptNumbers = {
	// Both Pair sides: Receipt rows edit credit_*, Payment rows edit debit_*.
	GRID_FIELDS: [
		"credit_amount", "credit_exchange_rate", "credit_company_amount",
		"debit_amount", "debit_exchange_rate", "debit_company_amount",
	],
	LIVE_FIELDS: ["credit_amount", "credit_exchange_rate", "debit_amount", "debit_exchange_rate", "receipt_payer_exchange_rate"],

	compact(formatted, df, doc) {
		const numeric = window.smartprocessAccounting?.numeric;
		if (!numeric || !frappe.boot?.smartprocess_accounting?.hide_insignificant_trailing_zeros) {
			return formatted;
		}
		const currency = df.fieldtype === "Currency" ? frappe.meta.get_field_currency(df, doc) : null;
		const decimal = get_number_format_info(get_number_format(currency)).decimal_str;
		return numeric.compactFormattedNumber(formatted, decimal);
	},

	formatter(value, df, options, doc) {
		const standard = { ...df, formatter: null };
		const formatted = frappe.form.get_formatter(df.fieldtype)(
			value,
			standard,
			{ ...(options || {}), inline: true, only_value: true },
			doc,
		);
		return spReceiptNumbers.compact(formatted, standard, doc);
	},

	// `state` is the caller's per-document state; another form passes its own.
	// The page-load boot payload is used when present, so no form needs an RPC.
	settings(frm, state = spReceiptForm.state(frm)) {
		if (!state.numberSettings) {
			const boot = frappe.boot?.smartprocess_accounting?.live_number_separator;
			state.numberSettings = { enabled: 0, separator: ",", decimal_str: ".", group_str: ",", ...boot };
			if (boot) {
				return state.numberSettings;
			}
			frappe
				.xcall(SP_RECEIPT_NUMBER_SETTINGS_METHOD)
				.then((settings) => {
					if (settings && typeof settings === "object") {
						Object.assign(state.numberSettings, settings);
					}
				})
				.catch(() => {});
		}
		return state.numberSettings;
	},

	install(frm) {
		this.prepare(frm, frm.fields_dict.receipt_payer_exchange_rate);
		const wrapper = frm.fields_dict[spReceiptConfig.TABLE]?.$wrapper?.get(0);
		if (!wrapper || spReceiptNumberWrappers.has(wrapper)) {
			return;
		}
		spReceiptNumberWrappers.add(wrapper);
		// Grid cell controls and the row form are built lazily; every numeric control
		// of the row is prepared when the row is clicked or focused. A read-only cell
		// (Base Amount) never gets focus itself, and in an editable grid row Frappe
		// renders it through format_for_input(), not frappe.format(). The grid column
		// click handler returns false (stops propagation), so the click is caught in
		// the capture phase and handled after that handler has built the controls.
		const prepareRow = (target) => {
			if (!spReceiptConfig.isFlow(frm.doc)) {
				return;
			}
			for (const control of this.rowControls(target)) {
				this.prepare(frm, control);
			}
		};
		wrapper.addEventListener("click", (event) => setTimeout(() => prepareRow(event.target)), true);
		wrapper.addEventListener("focusin", (event) => prepareRow(event.target));
	},

	rowControls(target) {
		const gridRow = $(target).closest(".grid-row").data("grid_row");
		if (!gridRow) {
			return [];
		}
		return this.GRID_FIELDS.flatMap((fieldname) => [
			gridRow.on_grid_fields_dict?.[fieldname],
			gridRow.grid_form?.fields_dict?.[fieldname],
		]).filter(Boolean);
	},

	controlFor(target, fieldname) {
		const holder = target?.closest?.(`[data-fieldname="${fieldname}"]`);
		if (!holder) {
			return null;
		}
		const gridRow = $(holder).closest(".grid-row").data("grid_row");
		return gridRow?.on_grid_fields_dict?.[fieldname] || gridRow?.grid_form?.fields_dict?.[fieldname] || null;
	},

	// The Receipt form uses the defaults; the Conversion form passes its own live
	// fieldnames and per-document state.
	prepare(frm, control, { live = this.LIVE_FIELDS, state } = {}) {
		if (!control?.format_for_input || !["Currency", "Float"].includes(control.df?.fieldtype)) {
			return;
		}
		if (!spReceiptCompactControls.has(control)) {
			spReceiptCompactControls.add(control);
			const formatForInput = control.format_for_input;
			control.format_for_input = function (value) {
				return spReceiptNumbers.compact(formatForInput.call(this, value), this.df, this.doc || this.frm?.doc);
			};
			if (control.$input) {
				control.set_formatted_input(control.value);
			}
		}
		if (live.includes(control.df.fieldname)) {
			const config = this.settings(frm, state);
			window.smartprocessAccounting?.numeric?.liveNumberSeparator?.attach(control, () => config);
		}
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = spReceiptNumbers;
}
