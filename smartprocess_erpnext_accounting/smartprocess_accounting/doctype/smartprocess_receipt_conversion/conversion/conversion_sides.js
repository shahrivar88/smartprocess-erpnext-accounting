// Receipt mode shows one section per source side. Each section lists its source
// rows read-only and edits only the target columns of the same stored `legs` rows.
const spConversionSides = {
	SIDES: {
		Receiver: { field: "receiver_conversion_html", party: "دریافت‌کننده" },
		Payer: { field: "payer_conversion_html", party: "پرداخت‌کننده" },
	},
	EDIT_COLUMNS: [
		["conversion_amount", 2],
		["target_rate", 1],
		["target_amount", 2],
		["target_party_type", 1],
		["target_party", 2],
		["target_account", 2],
	],
	SOURCE_AMOUNTS: [
		["original_amount", "مبلغ اصلی"],
		["already_converted", "قبلاً تبدیل‌شده"],
		["remaining_amount", "مانده قابل تبدیل"],
	],
	TEXT: {
		account: "حساب مبدا",
		targetAccount: "حساب مقصد",
		fill: "کل مانده",
		empty: "پس از انتخاب «رسید مبدا» و «ارز مقصد»، ردیف‌های این بخش اینجا نمایش داده می‌شود.",
	},

	isReceiptMode(doc) {
		return doc?.conversion_mode !== "Balance";
	},

	rows(frm, side) {
		return this.isReceiptMode(frm.doc) ? (frm.doc[spConversionLegs.TABLE] || []).filter((row) => row.source_side === side) : [];
	},

	editableFields() {
		return this.EDIT_COLUMNS.map(([fieldname, columns]) => ({ fieldname, columns }));
	},

	// `format(fieldname, row)` returns display HTML; every other cell is escaped here.
	sourceHtml(rows, side, { editable, format, titleOf }) {
		const escape = (text) => frappe.utils.escape_html(text ?? "");
		if (!rows.length) {
			return `<div class="text-muted small">${escape(this.TEXT.empty)}</div>`;
		}
		const heads = ["#", this.SIDES[side].party, this.TEXT.account, ...this.SOURCE_AMOUNTS.map(([, label]) => label)];
		const head = heads.map((label) => `<th>${escape(label)}</th>`).join("") + (editable ? "<th></th>" : "");
		const body = rows
			.map((row, index) => {
				const party = row.source_party ? titleOf(row.source_party_type, row.source_party) || row.source_party : "—";
				const amounts = this.SOURCE_AMOUNTS.map(([fieldname]) => `<td class="text-right">${format(fieldname, row)}</td>`);
				const fill = editable
					? `<td><button type="button" class="btn btn-xs btn-default" data-sp-fill="${escape(row.name)}">${escape(this.TEXT.fill)}</button></td>`
					: "";
				return `<tr><td>${index + 1}</td><td>${escape(party)}</td><td>${escape(row.source_account)}</td>${amounts.join("")}${fill}</tr>`;
			})
			.join("");
		return `<table class="table table-bordered table-sm small sp-conversion-source"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
	},

	setup(frm) {
		this.frm = frm;
		if (this.watching || !frappe.model?.on) {
			return;
		}
		this.watching = true;
		// Frappe updates only the native `legs` grid when a row value changes.
		frappe.model.on(spConversionLegs.LEG, "*", (fieldname, value, doc) => {
			if (doc?.parent === this.frm?.docname) {
				for (const grid of this.grids(this.frm)) {
					grid.set_value(fieldname, value, doc);
				}
			}
		});
	},

	grids(frm) {
		return Object.values(frm.__sp_sides || {}).map((entry) => entry.control.grid);
	},

	refresh(frm) {
		if (!this.isReceiptMode(frm.doc)) {
			return;
		}
		this.prepareColumns(frm);
		for (const side of Object.keys(this.SIDES)) {
			const entry = this.ensureGrid(frm, side);
			if (!entry) {
				continue;
			}
			entry.source.html(this.sourceHtml(this.rows(frm, side), side, this.sourceOptions(frm)));
			entry.control.grid.visible_columns = null;
			entry.control.grid.refresh();
		}
	},

	sourceOptions(frm) {
		return {
			editable: frm.doc.docstatus === 0,
			titleOf: (partyType, party) => spConversionForm.titleOf(partyType, party),
			format: (fieldname, row) =>
				frappe.format(row[fieldname], frappe.meta.get_docfield(spConversionLegs.LEG, fieldname, frm.docname), { inline: true }, row),
		};
	},

	// Grid widths and the plain Target Account label for this document only.
	prepareColumns(frm) {
		for (const [fieldname, columns] of this.EDIT_COLUMNS) {
			const df = frappe.meta.get_docfield(spConversionLegs.LEG, fieldname, frm.docname);
			if (df) {
				df.columns = columns;
			}
		}
		const account = frappe.meta.get_docfield(spConversionLegs.LEG, "target_account", frm.docname);
		if (account) {
			account.label = this.TEXT.targetAccount;
		}
	},

	ensureGrid(frm, side) {
		frm.__sp_sides = frm.__sp_sides || {};
		if (frm.__sp_sides[side]) {
			return frm.__sp_sides[side];
		}
		const wrapper = frm.fields_dict[this.SIDES[side].field]?.$wrapper;
		const legs = frm.fields_dict[spConversionLegs.TABLE];
		if (!wrapper || !legs?.grid) {
			return null;
		}
		const source = $("<div>").appendTo(wrapper);
		const control = frappe.ui.form.make_control({
			df: { fieldname: spConversionLegs.TABLE, fieldtype: "Table", options: spConversionLegs.LEG, label: "", cannot_add_rows: 1, cannot_delete_rows: 1 },
			parent: $("<div>").appendTo(wrapper),
			frm,
			render_input: false,
		});
		const grid = control.grid;
		// Grid swaps in the `legs` docfield on every refresh; that field is hidden in
		// Receipt mode, which would stop this grid from drawing.
		const df = grid.df;
		const setupFields = grid.setup_fields.bind(grid);
		grid.setup_fields = () => {
			setupFields();
			grid.df = df;
		};
		const refresh = grid.refresh.bind(grid);
		grid.refresh = (...args) => {
			const result = refresh(...args);
			this.numberRows(grid);
			return result;
		};
		grid.editable_fields = this.editableFields();
		grid.fieldinfo = legs.grid.fieldinfo;
		grid.get_data = () => this.rows(frm, side);
		// Dragging a filtered row would renumber the rows of the other side too.
		grid.sortable_setup_done = true;
		wrapper.on("click", "[data-sp-fill]", (event) =>
			spConversionForm.fillRemaining(frm, spConversionLegs.LEG, event.currentTarget.dataset.spFill),
		);
		spConversionForm.installNumbers(frm, control.$wrapper.get(0));
		frm.__sp_sides[side] = { control, source };
		return frm.__sp_sides[side];
	},

	// Display only: each side counts its own rows from 1. `idx` and `data-idx` keep
	// the stored position, which Frappe and the ledger links rely on.
	numberRows(grid) {
		for (const row of grid.grid_rows || []) {
			if (!row.__sp_local_number) {
				const setRowIndex = row.set_row_index.bind(row);
				row.set_row_index = () => {
					setRowIndex();
					this.numberRow(grid, row);
				};
				row.__sp_local_number = true;
			}
			this.numberRow(grid, row);
		}
	},

	numberRow(grid, row) {
		const number = grid.grid_rows.indexOf(row) + 1;
		if (number > 0) {
			row.wrapper?.find(".row-index span, .grid-form-row-index, .template-row-index span").text(number);
		}
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = spConversionSides;
}
