// Receipt validation UX. Checks run only at Add Row and Save/Submit, use the
// server preview contract, and show one message per check.
const spReceiptGuardedGrids = new WeakSet();

const spReceiptValidation = {
	// A row with only the default type (and its mirrored currency) is an
	// untouched placeholder; only the row side counts as user input.
	rowHasUserContent(row, doc = null) {
		const field = (name) => spReceiptConfig.rowField(doc, name);
		return Boolean(
			row?.receipt_recipient
			|| row?.[field("account")]
			|| Number(row?.[field("amount")])
			|| row?.[field("description")],
		);
	},

	rowIssues(preview, number) {
		return (preview?.issues || []).filter((issue) => issue.row === number);
	},

	plainText(message) {
		return String(message ?? "").replace(/<[^>]*>/g, "");
	},

	messageLines(issues, escape = (value) => frappe.utils.escape_html(value)) {
		const lines = [];
		for (const issue of issues) {
			const text = escape(this.plainText(issue.message));
			const line = issue.row ? `ردیف ${issue.row}: ${text}` : text;
			if (!lines.includes(line)) {
				lines.push(line);
			}
		}
		return lines;
	},

	show(title, issues) {
		frappe.msgprint({
			title,
			indicator: "orange",
			message: this.messageLines(issues).join("<br>"),
		});
	},

	// Grid offers no before-add hook; Add Row and Duplicate both go through
	// add_new_row, so the last row is checked there.
	installAddRowGuard(frm) {
		const grid = frm.fields_dict[spReceiptConfig.TABLE]?.grid;
		if (!grid || spReceiptGuardedGrids.has(grid)) {
			return;
		}
		spReceiptGuardedGrids.add(grid);
		const addNewRow = grid.add_new_row;
		grid.add_new_row = function (...args) {
			const rows = this.frm.doc[spReceiptConfig.TABLE] || [];
			const last = rows[rows.length - 1];
			if (!spReceiptConfig.isFlow(this.frm.doc) || !spReceiptValidation.rowHasUserContent(last, this.frm.doc)) {
				return addNewRow.apply(this, args);
			}
			spReceiptValidation.addAfterCheck(this.frm, rows.length, () => {
				addNewRow.apply(this, args);
				this.set_focus_on_row?.();
			});
		};
	},

	async addAfterCheck(frm, number, addRow) {
		const state = spReceiptForm.state(frm);
		if (state.addingRow) {
			return;
		}
		state.addingRow = true;
		try {
			const issues = this.rowIssues(await spReceiptSummary.refreshNow(frm), number);
			if (issues.length) {
				this.show(__("ردیف {0} کامل نیست", [number]), issues);
				return;
			}
			addRow();
		} finally {
			state.addingRow = false;
		}
	},

	// Untouched placeholder rows are dropped while real rows exist; the server
	// stays the authority for the complete check.
	dropPlaceholderRows(frm) {
		const rows = frm.doc[spReceiptConfig.TABLE] || [];
		const placeholders = rows.filter((row) => !this.rowHasUserContent(row, frm.doc));
		if (!placeholders.length || placeholders.length === rows.length) {
			return;
		}
		for (const row of placeholders) {
			frappe.model.clear_doc(row.doctype, row.name);
		}
		frm.refresh_field(spReceiptConfig.TABLE);
	},

	async validateSave(frm) {
		this.dropPlaceholderRows(frm);
		const preview = await spReceiptSummary.refreshNow(frm);
		if (!preview || preview.ready) {
			return;
		}
		frappe.validated = false;
		this.show(__(spFlowText.of(frm.doc).incomplete), preview.issues || []);
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = spReceiptValidation;
}
