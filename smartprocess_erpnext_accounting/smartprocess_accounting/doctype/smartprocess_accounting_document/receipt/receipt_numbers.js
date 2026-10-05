// Receipt number display: compact decimals (no trailing zeros) and the live
// thousands separator. Presentation only — model values stay raw numbers.
const SP_RECEIPT_NUMBER_SETTINGS_METHOD =
	"smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_accounting_settings.smartprocess_accounting_settings.get_number_input_settings";
const spReceiptCompactControls = new WeakSet();
const spReceiptNumberWrappers = new WeakSet();

const spReceiptNumbers = {
	GRID_FIELDS: ["credit_amount", "credit_exchange_rate", "credit_company_amount"],
	LIVE_FIELDS: ["credit_amount", "credit_exchange_rate", "receipt_payer_exchange_rate"],

	compact(formatted, df, doc) {
		const numeric = window.smartprocessAccounting?.numeric;
		if (!numeric) {
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

	settings(frm) {
		const state = spReceiptForm.state(frm);
		if (!state.numberSettings) {
			state.numberSettings = { enabled: 0, separator: ",", decimal_str: ".", group_str: "," };
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
		// Grid cell controls and the row form are built lazily; they are prepared
		// when they receive focus, before the user can type.
		wrapper.addEventListener("focusin", (event) => {
			if (!spReceiptConfig.isReceipt(frm.doc)) {
				return;
			}
			for (const fieldname of this.GRID_FIELDS) {
				const control = this.controlFor(event.target, fieldname);
				if (control) {
					this.prepare(frm, control);
				}
			}
		});
	},

	controlFor(target, fieldname) {
		const holder = target?.closest?.(`[data-fieldname="${fieldname}"]`);
		if (!holder) {
			return null;
		}
		const gridRow = $(holder).closest(".grid-row").data("grid_row");
		return gridRow?.on_grid_fields_dict?.[fieldname] || gridRow?.grid_form?.fields_dict?.[fieldname] || null;
	},

	prepare(frm, control) {
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
		if (this.LIVE_FIELDS.includes(control.df.fieldname)) {
			const config = this.settings(frm);
			window.smartprocessAccounting?.numeric?.liveNumberSeparator?.attach(control, () => config);
		}
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = spReceiptNumbers;
}
