// Header fields that steer every row: the one row currency all rows inherit
// (Receipt payers / Payment recipients), and the date new rows start from.
const spReceiptPayerHeader = {
	// A new Receipt pays in Company.default_currency; a Receipt saved before the
	// header field existed takes the single currency its rows already use.
	async applyDefault(frm, replace) {
		const companyCurrency = frm.doc.company_currency;
		const state = spReceiptForm.state(frm);
		if (!companyCurrency || frm.doc.docstatus !== 0) {
			state.payerCurrency = frm.doc[spReceiptConfig.PAYER_CURRENCY] || "";
			return;
		}
		const current = frm.doc[spReceiptConfig.PAYER_CURRENCY] || "";
		let currency = current;
		if (!current) {
			currency = this.rowCurrency(frm) || companyCurrency;
		} else if (replace && !spReceiptRowEvents.rows(frm).some((row) => spReceiptValidation.rowHasUserContent(row, frm.doc))) {
			currency = companyCurrency;
		}
		if (current !== currency) {
			spReceiptHeader.applyCurrencyOptions(frm, [currency, ...(state.currencyOptions?.values || [])]);
			await spReceiptForm.quietly(frm, () => frm.set_value(spReceiptConfig.PAYER_CURRENCY, currency));
		}
		state.payerCurrency = currency;
	},

	rowCurrency(frm) {
		const used = new Set(spReceiptRowEvents.rows(frm).map((row) => row.receipt_currency).filter(Boolean));
		return used.size === 1 ? [...used][0] : "";
	},

	async companyChanged(frm) {
		await this.applyDefault(frm, true);
		await spReceiptRowEvents.syncPayerCurrency(frm);
		spReceiptForm.configureGrid(frm, true);
	},

	// Rows filled in another currency lose only their payer, ledger and rate,
	// and only after the user confirms.
	async currencyChanged(frm) {
		if (spReceiptForm.isQuiet(frm)) {
			return;
		}
		const state = spReceiptForm.state(frm);
		const previous = state.payerCurrency;
		const current = frm.doc[spReceiptConfig.PAYER_CURRENCY] || "";
		if (previous === current) {
			return;
		}
		const affected = spReceiptRowEvents.rowsLosingValues(frm, current);
		if (affected.length && !(await this.confirmChange(previous, current, affected.length, undefined, frm.doc))) {
			await spReceiptForm.quietly(frm, () => frm.set_value(spReceiptConfig.PAYER_CURRENCY, previous));
			return;
		}
		state.payerCurrency = current;
		await spReceiptRowEvents.syncPayerCurrency(frm);
		spReceiptForm.configureGrid(frm, true);
		spReceiptSummary.schedule(frm);
	},

	confirmChange(previous, current, count, escape = (value) => frappe.utils.escape_html(value), doc = null) {
		const message = __(spFlowText.of(doc).currencyChange, [escape(previous || "—"), escape(current || "—"), count]);
		return new Promise((resolve) => {
			frappe.confirm(message, () => resolve(true), () => resolve(false));
		});
	},

	async postingDateChanged(frm) {
		const state = spReceiptForm.state(frm);
		const previous = state.postingDate;
		const date = frm.doc.posting_date || "";
		state.postingDate = date;
		if (previous !== date && frm.doc.docstatus === 0) {
			const kept = await spReceiptRowEvents.postingDateChanged(frm, previous);
			if (kept.length) {
				this.warnRowDates();
			}
		}
		spReceiptSummary.schedule(frm);
	},

	warnRowDates() {
		frappe.msgprint({
			title: __("تاریخ ردیف‌ها تغییر نکرد"),
			indicator: "orange",
			message: __("تاریخ عملیات ردیف‌های موجود قبلاً تعیین شده است و با تاریخ جدید سند همگام نمی‌شود. ردیف‌هایی که از این پس اضافه شوند، تاریخ جدید سند را می‌گیرند."),
		});
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = spReceiptPayerHeader;
}
