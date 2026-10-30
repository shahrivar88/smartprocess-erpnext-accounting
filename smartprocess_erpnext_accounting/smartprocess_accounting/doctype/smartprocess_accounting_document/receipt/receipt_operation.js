// Receipt ↔ Payment switch: confirm before dropping the old side, move the
// shared row values onto the new debit/credit side, then rebuild the form.
const SP_MOVED_SIDE_FIELDS = [
	"account", "suggested_account", "party_type", "party", "account_currency",
	"amount", "exchange_rate", "company_amount", "rate_direction", "description",
];

const spReceiptOperation = {
	async changed(frm) {
		if (frm.doc.docstatus !== 0 || spReceiptForm.isQuiet(frm)) {
			return;
		}
		const state = spReceiptForm.state(frm);
		const previous = state.operationType;
		const current = frm.doc.operation_type || "";
		if (previous === current) {
			return this.rebuild(frm);
		}
		if (this.hasEnteredValues(frm, previous) && !(await this.confirm(previous, current))) {
			await spReceiptForm.quietly(frm, () => frm.set_value("operation_type", previous));
			return;
		}
		await this.retargetSides(frm, previous, current);
		state.operationType = current;
		return this.rebuild(frm);
	},

	hasEnteredValues(frm, operationType) {
		const previous = { ...frm.doc, operation_type: operationType || frm.doc.operation_type };
		if (spReceiptHeader.hasReceiptData(previous)) {
			return true;
		}
		const side = spReceiptConfig.ROW_SIDES[operationType];
		return Boolean(side && (frm.doc[spReceiptConfig.TABLE] || []).some((row) =>
			row[`${side}_account`] || Number(row[`${side}_amount`]) || row[`${side}_description`],
		));
	},

	confirm(previous, current, escape = (value) => frappe.utils.escape_html(value)) {
		const label = (type) => (type === "Payment" ? "پرداخت" : type === "Receipt" ? "دریافت" : type || "—");
		const message = __(spFlowText.of({ operation_type: current }).operationChange, [
			escape(label(previous)),
			escape(label(current)),
		]);
		return new Promise((resolve) => {
			frappe.confirm(message, () => resolve(true), () => resolve(false));
		});
	},

	async retargetSides(frm, previous, current) {
		const from = spReceiptConfig.ROW_SIDES[previous];
		const to = spReceiptConfig.ROW_SIDES[current];
		if (!from || !to || from === to) {
			return;
		}
		await spReceiptForm.quietly(frm, async () => {
			for (const row of spReceiptRowEvents.rows(frm)) {
				for (const name of SP_MOVED_SIDE_FIELDS) {
					await spReceiptRowEvents.setRowValue(row, `${to}_${name}`, row[`${from}_${name}`] ?? null);
					await spReceiptRowEvents.setRowValue(row, `${from}_${name}`, null);
				}
			}
		});
	},

	async rebuild(frm) {
		this.closeGrid(frm);
		await spReceiptForm.refresh(frm);
		const grid = frm.fields_dict[spReceiptConfig.TABLE]?.grid;
		if (grid) {
			grid.visible_columns = [];
			for (const docfield of grid.docfields || []) {
				if (grid.fields_map) {
					grid.fields_map[docfield.fieldname] = docfield;
				}
			}
			grid.reset_grid();
		}
		frm.refresh_field?.(spReceiptConfig.TABLE);
		frm.refresh_fields?.();
		spReceiptRowQueries.installPayerTypeOrder(frm);
	},

	closeGrid(frm) {
		const grid = frm.fields_dict[spReceiptConfig.TABLE]?.grid;
		const open = grid?.open_grid_row;
		if (!open) {
			return;
		}
		if (typeof open.toggle_view === "function") {
			open.toggle_view(false);
		} else if (typeof open.hide_form === "function") {
			open.hide_form();
		}
		grid.open_grid_row = null;
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = spReceiptOperation;
}
