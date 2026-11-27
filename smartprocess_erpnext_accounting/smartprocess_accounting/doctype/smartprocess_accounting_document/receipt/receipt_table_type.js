// The party type control above the rows mirrors the LAST row's type. It is a
// UI helper only: every row keeps its own type/name/account and is the source
// of truth for posting. Changing the helper never touches earlier rows.
const spReceiptTableType = {
	field: "receipt_row_party_type",

	rows(frm) {
		return frm.doc[spReceiptConfig.TABLE] || [];
	},

	lastRow(frm) {
		const rows = this.rows(frm);
		return rows.length ? rows[rows.length - 1] : null;
	},

	value(frm) {
		return (frm.doc[this.field] || "").trim();
	},

	async initialize(frm) {
		if (!spReceiptConfig.isFlow(frm.doc)) {
			return;
		}
		frm.set_df_property(this.field, "label", spFlowText.of(frm.doc).rows.receipt_recipient_type);
		frm.set_query(this.field, () => ({
			query: spReceiptConfig.method("v2_api.receipt_recipient_type_query"),
		}));
		await this.syncFromLastRow(frm);
	},

	async setHelper(frm, value) {
		if (this.value(frm) === (value || "")) {
			return;
		}
		await spReceiptForm.quietly(frm, () =>
			frappe.model.set_value(frm.doctype, frm.doc.name, this.field, value || ""),
		);
	},

	async syncFromLastRow(frm) {
		const row = this.lastRow(frm);
		await this.setHelper(frm, row ? row.receipt_recipient_type : "");
	},

	// Changing the helper retargets only the last row; its amount and
	// description stay, while a name/account for the old type cannot.
	async changed(frm) {
		if (frm.doc.docstatus !== 0 || spReceiptForm.isQuiet(frm) || !spReceiptConfig.isFlow(frm.doc)) {
			return;
		}
		const row = this.lastRow(frm);
		if (!row) {
			return;
		}
		const type = this.value(frm);
		if ((row.receipt_recipient_type || "") === type) {
			return;
		}
		await spReceiptForm.quietly(frm, async () => {
			await spReceiptRowEvents.setRowValue(row, "receipt_recipient_type", type || null);
			await spReceiptRowEvents.setRowValue(row, "receipt_recipient", "");
			await spReceiptRowEvents.setRowValue(row, spReceiptConfig.rowField(frm.doc, "account"), "");
		});
		spReceiptSummary.schedule(frm);
	},

	// A new row starts from the helper value (or the configured default).
	async rowAdded(frm, row) {
		if (!spReceiptConfig.isFlow(frm.doc)) {
			return;
		}
		const type = this.value(frm) || spReceiptForm.state(frm).payerTypeDefault || "";
		if (type && !row.receipt_recipient_type) {
			await spReceiptRowEvents.setRowValue(row, "receipt_recipient_type", type);
		}
		await this.syncFromLastRow(frm);
	},

	// Editing any row's type updates the helper only for the last row.
	async rowTypeChanged(frm, row) {
		if (frm.doc.docstatus !== 0 || !spReceiptConfig.isFlow(frm.doc)) {
			return;
		}
		if (row === this.lastRow(frm)) {
			await this.setHelper(frm, row.receipt_recipient_type || "");
		}
	},

	async rowRemoved(frm) {
		if (frm.doc.docstatus !== 0) {
			return;
		}
		await this.syncFromLastRow(frm);
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = spReceiptTableType;
}
