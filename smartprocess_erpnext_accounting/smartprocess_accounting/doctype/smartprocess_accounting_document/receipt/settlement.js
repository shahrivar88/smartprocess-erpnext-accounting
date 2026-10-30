const spReceiptSettlement = {
	refresh(frm) {
		if (!spReceiptConfig.isFlow(frm.doc) || frm.doc.docstatus) {
			return;
		}
		if (!this.enabled()) {
			return;
		}
		this.schedule(frm);
	},

	enabled() {
		return Boolean(Number(frappe.boot?.smartprocess_accounting?.payment_entry_settlement));
	},

	schedule(frm) {
		const state = spReceiptForm.state(frm);
		clearTimeout(state.settlementTimer);
		state.settlementTimer = setTimeout(() => this.load(frm), 200);
	},

	async load(frm) {
		if (!frm.fields_dict.settlement_summary) {
			return;
		}
		try {
			const preview = await frappe.xcall(
				spReceiptConfig.method("settlement.api.preview_settlement"),
				{ doc: frm.doc },
			);
			this.render(frm, preview);
		} catch (error) {
			frm.fields_dict.settlement_summary.$wrapper.empty();
		}
	},

	render(frm, preview) {
		const wrap = frm.fields_dict.settlement_summary.$wrapper;
		if (!preview || preview.eligible === false) {
			wrap.html(preview?.reason ? `<p class="text-muted">${frappe.utils.escape_html(preview.reason)}</p>` : "");
			return;
		}
		if (preview.error) {
			wrap.html(`<p class="text-danger">${frappe.utils.escape_html(preview.error)}</p>`);
			return;
		}
		wrap.html(`
			<div class="sp-settlement-preview">
				<p>${__("مبلغ سند")}: ${frappe.utils.escape_html(preview.amount)} ${frappe.utils.escape_html(preview.currency)}</p>
				<p>${__("فاکتورهای قابل تسویه")}: ${frappe.utils.escape_html(String(preview.open_invoice_count))}</p>
				<p>${__("مبلغ تخصیص‌یافته")}: ${frappe.utils.escape_html(preview.allocated)}</p>
				<p>${__("مانده فاکتورهای انتخاب‌شده")}: ${frappe.utils.escape_html(preview.invoice_remaining)}</p>
				<p>${__("اعتبار آزاد")}: ${frappe.utils.escape_html(preview.unallocated)}</p>
			</div>
		`);
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = spReceiptSettlement;
}
