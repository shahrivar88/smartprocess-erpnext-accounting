// Receipt / Payment preview and summary. The server preview is the only source
// of financial values: the row-currency total, its weighted rate, the derived
// header amount and each row's base amount.
const SP_RECEIPT_PREVIEW_DELAY = 400;

const spReceiptSummary = {
	payload(doc) {
		const field = (name) => spReceiptConfig.rowField(doc, name);
		return {
			doctype: doc.doctype,
			name: doc.name,
			operation_type: doc.operation_type,
			company: doc.company,
			posting_date: doc.posting_date,
			receipt_receiver_kind: doc.receipt_receiver_kind,
			receipt_payer_type: doc.receipt_payer_type,
			receipt_payer: doc.receipt_payer,
			receipt_bank_account: doc.receipt_bank_account,
			receipt_payer_currency: doc.receipt_payer_currency,
			receipt_payer_exchange_rate: doc.receipt_payer_exchange_rate,
			receipt_payer_account: doc.receipt_payer_account,
			receipt_credit_currency: doc.receipt_credit_currency,
			operational_pairs: (doc[spReceiptConfig.TABLE] || []).map((row) => ({
				doctype: row.doctype,
				name: row.name,
				receipt_posting_date: row.receipt_posting_date,
				receipt_recipient_type: row.receipt_recipient_type,
				receipt_recipient: row.receipt_recipient,
				receipt_currency: row.receipt_currency,
				...Object.fromEntries(["account", "amount", "exchange_rate", "description"].map((name) => [field(name), row[field(name)]])),
			})),
		};
	},

	canPreview(frm) {
		return spReceiptConfig.isFlow(frm.doc)
			&& Boolean(frappe.model.can_write(frm.doctype) || frappe.model.can_create(frm.doctype));
	},

	schedule(frm, delay = SP_RECEIPT_PREVIEW_DELAY) {
		const state = spReceiptForm.state(frm);
		clearTimeout(state.previewTimer);
		if (!this.canPreview(frm)) {
			return;
		}
		state.previewTimer = setTimeout(() => {
			this.refreshNow(frm).catch(() => {});
		}, delay);
	},

	async refreshNow(frm) {
		const state = spReceiptForm.state(frm);
		clearTimeout(state.previewTimer);
		if (!this.canPreview(frm)) {
			return null;
		}
		const request = ++state.previewRequest;
		const payload = this.payload(frm.doc);
		const preview = await frappe.xcall(spReceiptConfig.method(spFlowText.of(frm.doc).preview), { doc: payload });
		if (request === state.previewRequest && state === spReceiptForm.state(frm)) {
			state.preview = preview;
			await this.applyRowAmounts(frm, payload, preview);
			this.render(frm);
		}
		return preview;
	},

	// Base Amount is display-only and comes from the preview; rows that are not
	// valid yet show no base amount.
	async applyRowAmounts(frm, payload, preview) {
		if (frm.doc.docstatus !== 0 || !preview) {
			return;
		}
		const byName = new Map();
		for (const entry of preview.rows || []) {
			const row = payload.operational_pairs[entry.row - 1];
			if (row) {
				byName.set(row.name, Number(entry.base_amount));
			}
		}
		const baseField = spReceiptConfig.rowField(frm.doc, "company_amount");
		for (const row of frm.doc[spReceiptConfig.TABLE] || []) {
			const value = byName.has(row.name) ? byName.get(row.name) : null;
			const current = row[baseField];
			const same = value === null ? !Number(current) : Number(current) === value && current !== "";
			if (!same) {
				await frappe.model.set_value(row.doctype, row.name, baseField, value);
			}
		}
	},

	render(frm) {
		const field = frm.fields_dict.receipt_summary;
		if (!field) {
			return;
		}
		field.$wrapper.html(this.html(spReceiptForm.state(frm).preview, frm.doc));
	},

	formatNumber(value) {
		return spReceiptNumbers.formatter(value, { fieldtype: "Float", precision: 9 }, {}, {});
	},

	html(preview, doc, format = (value) => this.formatNumber(value), escape = (value) => frappe.utils.escape_html(value)) {
		const result = preview || {};
		const companyCurrency = escape(result.company_currency || doc.company_currency || "");
		const number = (value) => (value == null || value === "" ? "—" : format(value));
		const base = (value) => (value == null || value === "" ? "—" : `${format(value)} ${companyCurrency}`.trim());
		const row = (className, cells) => `<tr class="${className}">${cells.map((cell) => `<td>${cell}</td>`).join("")}</tr>`;
		const payers = (result.payer_totals || []).map((total) =>
			row("sp-receipt-payer-values", [escape(total.currency), number(total.amount), number(total.rate), base(total.base_amount)]),
		);
		const text = spFlowText.of(doc);
		const receiverCurrency = result.receiver_currency || doc.receipt_payer_currency || "";
		const receiver = result.receiver_account || doc.receipt_payer_account || "";
		const receiverTitle = receiver ? `${text.summaryTitle} — ${escape(receiver)}` : text.summaryTitle;
		return `<div class="sp-receipt-summary">
			<table class="table table-bordered">
				<thead><tr><th>ارز</th><th>جمع به همان ارز</th><th>میانگین موزون نرخ</th><th>جمع به ارز پایه</th></tr></thead>
				<tbody class="sp-receipt-payers">${payers.join("") || row("sp-receipt-payer-values", ["—", "—", "—", "—"])}</tbody>
				<tbody class="sp-receipt-receiver">
					<tr class="sp-receipt-receiver-title"><th colspan="4">${receiverTitle}</th></tr>
					<tr class="sp-receipt-receiver-head"><th>${text.headerCurrency}</th><th>${text.headerAmount}</th><th>نرخ مؤثر</th><th>مبلغ به ارز پایه</th></tr>
					${row("sp-receipt-receiver-values", [
						escape(receiverCurrency || "—"),
						number(result.receiver_amount),
						number(result.receiver_effective_rate),
						base(result.receiver_base_amount),
					])}
				</tbody>
			</table>
		</div>`;
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = spReceiptSummary;
}
