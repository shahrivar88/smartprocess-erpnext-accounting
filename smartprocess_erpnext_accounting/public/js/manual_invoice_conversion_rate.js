frappe.provide("smartprocess_erpnext_accounting");

smartprocess_erpnext_accounting.manual_invoice_rate = {
	message: "نرخ تبدیل ارز را به‌صورت دستی وارد کنید.",

	company_currency(frm) {
		return frm.doc.company ? erpnext.get_currency(frm.doc.company) : "";
	},

	is_foreign(frm) {
		const company_currency = this.company_currency(frm);
		return !!(frm.doc.currency && company_currency && frm.doc.currency !== company_currency);
	},

	setup(frm) {
		frm._sp_clearing_rate = false;
		frm._sp_user_editing_rate = false;
		frm._sp_last_currency = frm.doc.currency;
		frm._sp_manual_rate = !frm.is_new() && flt(frm.doc.conversion_rate) > 0;
	},

	refresh(frm) {
		this.schedule_apply(frm);
		this.bind_input(frm);
	},

	decimal_separator() {
		const format = typeof get_number_format === "function" ? get_number_format() : "#,###.##";
		const info = typeof get_number_format_info === "function" ? get_number_format_info(format) : null;
		return (info && info.decimal_str) || ".";
	},

	strip_trailing_zeros(formatted) {
		if (!formatted) {
			return formatted;
		}
		const decimal = this.decimal_separator();
		if (!decimal) {
			return formatted;
		}
		const idx = String(formatted).lastIndexOf(decimal);
		if (idx < 0) {
			return formatted;
		}
		const int_part = formatted.slice(0, idx);
		const dec_part = formatted.slice(idx + decimal.length).replace(/0+$/, "");
		return dec_part ? int_part + decimal + dec_part : int_part;
	},

	install_display(ctrl) {
		if (!ctrl || ctrl._sp_trim_zeros) {
			return;
		}
		ctrl._sp_trim_zeros = true;
		const original_format = ctrl.format_for_input.bind(ctrl);
		ctrl.format_for_input = (value) => this.strip_trailing_zeros(original_format(value));
		const original_disp = ctrl.set_disp_area.bind(ctrl);
		ctrl.set_disp_area = function (value) {
			original_disp(value);
			if (this.disp_area) {
				$(this.disp_area).text(this.format_for_input(this.value ?? value));
			}
		};
		if (!ctrl.$input || !ctrl.$input.is(":focus")) {
			ctrl.set_formatted_input(ctrl.value);
			if (typeof ctrl.set_disp_area === "function") {
				ctrl.set_disp_area(ctrl.value);
			}
		}
	},

	apply_field(frm) {
		if (frm.doc.docstatus !== 0 || !this.is_foreign(frm)) {
			return;
		}
		frm.set_df_property("conversion_rate", "read_only", 0);
		frm.set_df_property("conversion_rate", "reqd", 1);
	},

	schedule_apply(frm) {
		this.apply_field(frm);
		frappe.after_ajax(() => {
			this.apply_field(frm);
			setTimeout(() => this.apply_field(frm), 50);
		});
	},

	bind_input(frm) {
		const ctrl = frm.fields_dict.conversion_rate;
		if (!ctrl) {
			return;
		}
		this.install_display(ctrl);
		if (ctrl._sp_rate_bound) {
			return;
		}
		const $input = ctrl.$input || (ctrl.$wrapper && ctrl.$wrapper.find("input"));
		if (!$input || !$input.length) {
			return;
		}
		ctrl._sp_rate_bound = true;
		$input.on("focus.sp_rate", () => {
			frm._sp_user_editing_rate = true;
		});
		$input.on("input.sp_rate change.sp_rate", () => {
			frm._sp_user_editing_rate = true;
			frm._sp_manual_rate = true;
		});
	},

	currency(frm) {
		if (frm.doc.docstatus !== 0 || !frm.is_new()) {
			return;
		}
		if (frm._sp_last_currency !== frm.doc.currency) {
			frm._sp_manual_rate = false;
			frm._sp_last_currency = frm.doc.currency;
		}
		this.schedule_apply(frm);
	},

	conversion_rate(frm) {
		if (frm._sp_clearing_rate || frm.doc.docstatus !== 0) {
			return;
		}
		if (frm._sp_user_editing_rate && flt(frm.doc.conversion_rate) > 0) {
			frm._sp_manual_rate = true;
			this.schedule_apply(frm);
			return;
		}
		if (frm.is_new() && !frm._sp_manual_rate && this.is_foreign(frm) && flt(frm.doc.conversion_rate) > 0) {
			frm._sp_clearing_rate = true;
			frm.set_value("conversion_rate", 0);
			frm._sp_clearing_rate = false;
		}
		this.schedule_apply(frm);
	},

	validate(frm) {
		if (!this.is_foreign(frm)) {
			return;
		}
		if (flt(frm.doc.conversion_rate) <= 0) {
			frappe.msgprint({
				message: __(this.message),
				indicator: "red",
			});
			frappe.validated = false;
		}
	},
};

["Sales Invoice", "Purchase Invoice"].forEach((doctype) => {
	frappe.ui.form.on(doctype, {
		setup(frm) {
			smartprocess_erpnext_accounting.manual_invoice_rate.setup(frm);
		},
		refresh(frm) {
			smartprocess_erpnext_accounting.manual_invoice_rate.refresh(frm);
		},
		currency(frm) {
			smartprocess_erpnext_accounting.manual_invoice_rate.currency(frm);
		},
		conversion_rate(frm) {
			smartprocess_erpnext_accounting.manual_invoice_rate.conversion_rate(frm);
		},
		validate(frm) {
			smartprocess_erpnext_accounting.manual_invoice_rate.validate(frm);
		},
	});
});
