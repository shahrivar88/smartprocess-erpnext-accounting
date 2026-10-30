// Receipt / Payment form orchestration: one state object per document, grid
// layout per operation type, and the entry points called from the form events.
// Rows fill one Pair side (Receipt: credit, Payment: debit); the server fills
// the other side from the header.
const SP_RECEIPT_GRID_FIELDS = ["receipt_posting_date", "receipt_recipient_type", "receipt_recipient", "receipt_currency"];
const SP_PAIR_SIDE_FIELDS = [
	"account_category", "account", "suggested_account", "party_type", "party", "account_currency",
	"amount", "exchange_rate", "company_amount", "rate_direction", "description",
];
const SP_ROW_SIDE_HIDDEN_FIELDS = ["account_category", "suggested_account", "party_type", "party", "account_currency", "rate_direction"];
const SP_ROW_SIDE_VISIBLE_FIELDS = ["account", "amount", "exchange_rate", "company_amount", "description"];
// Column sizes only; the column order stays the Pair metadata order. The row
// Exchange Rate column joins them only for a foreign row currency.
const SP_RECEIPT_LIST_COLUMNS = [
	["receipt_recipient_type", 2],
	["receipt_recipient", 4],
	["account", 3],
	["amount", 2],
	["company_amount", 2],
];
const SP_RECEIPT_RATE_COLUMNS = 2;
const SP_ROW_SIDE_LABELS = {
	amount: "مبلغ",
	exchange_rate: "نرخ ارز",
	company_amount: "مبلغ به ارز پایه",
	description: "توضیح",
};
const SP_RECEIPT_ROW_LABELS = {
	receipt_currency: "ارز",
	details_section: "جزئیات بیشتر",
	tracking_number: "شماره پیگیری",
	transfer_reference: "مرجع انتقال",
	cheque_number: "شماره چک",
	cheque_date: "تاریخ چک",
	bank_reference: "مرجع بانکی",
	deposit_identifier: "شناسه واریز",
	depositor_name: "نام واریزکننده",
	bank_name: "نام بانک / بانک مبدأ",
};
const spReceiptOwnedGrids = new WeakSet();

const spReceiptForm = {
	state(frm) {
		if (!frm.__sp_receipt || frm.__sp_receipt.docname !== frm.docname) {
			clearTimeout(frm.__sp_receipt?.previewTimer);
			frm.__sp_receipt = {
				docname: frm.docname,
				currency: frm.doc.receipt_payer_currency || "",
				payerCurrency: frm.doc.receipt_credit_currency || "",
				postingDate: frm.doc.posting_date || "",
				preview: null,
				previewRequest: 0,
				previewTimer: null,
				quiet: 0,
				addingRow: false,
				currencyOptions: null,
				payerTypeDefault: null,
				payerTypeOptions: null,
				numberSettings: null,
				operationType: frm.doc.operation_type || "",
			};
		}
		return frm.__sp_receipt;
	},

	isQuiet(frm) {
		return this.state(frm).quiet > 0;
	},

	// Programmatic cascades (clears, Add Row copy) run with the row handlers
	// muted so they do not react to their own writes.
	async quietly(frm, update) {
		const state = this.state(frm);
		state.quiet += 1;
		try {
			return await update();
		} finally {
			state.quiet -= 1;
		}
	},

	setup(frm) {
		this.applyOperationTypeOptions(frm);
		spReceiptHeader.setupQueries(frm);
		spReceiptRowQueries.setupQueries(frm);
	},

	applyOperationTypeOptions(frm) {
		frm.set_df_property("operation_type", "options", spReceiptConfig.operationTypeOptions(frm.doc));
	},

	async refresh(frm) {
		this.applyOperationTypeOptions(frm);
		const isFlow = spReceiptConfig.isFlow(frm.doc);
		const state = this.state(frm);
		if (!state.operationType) {
			state.operationType = frm.doc.operation_type || "";
		}
		spReceiptHeader.configure(frm, isFlow);
		this.configureGrid(frm, isFlow);
		if (!isFlow) {
			frm.fields_dict.receipt_summary?.$wrapper.empty();
			return;
		}
		spReceiptValidation.installAddRowGuard(frm);
		spReceiptNumbers.install(frm);
		spReceiptRowQueries.installPayerTypeOrder(frm);
		await spReceiptHeader.initialize(frm);
		await spReceiptRowEvents.initializeRows(frm);
		this.configureGrid(frm, isFlow);
		spReceiptSummary.render(frm);
		spReceiptSummary.schedule(frm, 0);
		spReceiptSettlement.refresh(frm);
	},

	validate(frm) {
		if (!spReceiptConfig.isFlow(frm.doc)) {
			return;
		}
		return spReceiptValidation.validateSave(frm);
	},

	configureGrid(frm, isFlow) {
		const field = frm.fields_dict[spReceiptConfig.TABLE];
		const grid = field?.grid;
		if (!grid) {
			return;
		}
		field.$wrapper.closest(".form-section").toggleClass("sp-receipt-layout-section", isFlow);
		field.$wrapper.toggleClass("sp-receipt-wide-grid", isFlow);
		frm.fields_dict.receipt_summary?.$wrapper.toggleClass("sp-receipt-wide-grid", isFlow);
		this.ownColumns(grid);
		const properties = isFlow ? this.receiptGridProperties(frm.doc) : this.genericGridProperties();
		const latest = new Map(properties.map(([fieldname, property, value]) => [`${fieldname}:${property}`, [fieldname, property, value]]));
		let changed = false;
		for (const [fieldname, property, value] of latest.values()) {
			changed = this.setGridProperty(frm, grid, fieldname, property, value) || changed;
		}
		if (changed) {
			grid.visible_columns = [];
		}
		if (changed && !grid.open_grid_row && !document.querySelector(".jalali-picker:not(.pwt-hide)")) {
			grid.reset_grid();
		}
	},

	// The row Currency mirrors the header row currency: shown read-only in the
	// row form, never as a grid column. The header side is never edited in a row.
	receiptGridProperties(doc = {}) {
		const side = spReceiptConfig.rowSide(doc);
		const headerSide = side === "credit" ? "debit" : "credit";
		const row = (name) => `${side}_${name}`;
		const text = spFlowText.of(doc);
		const properties = [];
		for (const name of SP_PAIR_SIDE_FIELDS) {
			properties.push(
				[`${headerSide}_${name}`, "hidden", 1],
				[`${headerSide}_${name}`, "reqd", 0],
				[`${headerSide}_${name}`, "in_list_view", 0],
			);
		}
		for (const name of SP_ROW_SIDE_VISIBLE_FIELDS) {
			properties.push([row(name), "hidden", 0]);
		}
		for (const fieldname of ["credit_column", "receipt_payer_exchange_rate", ...SP_ROW_SIDE_HIDDEN_FIELDS.map(row)]) {
			properties.push([fieldname, "hidden", 1], [fieldname, "in_list_view", 0]);
		}
		for (const fieldname of SP_RECEIPT_GRID_FIELDS) {
			properties.push([fieldname, "hidden", 0]);
		}
		for (const fieldname of ["receipt_posting_date", "receipt_currency", row("description")]) {
			properties.push([fieldname, "in_list_view", 0]);
		}
		for (const [name, columns] of SP_RECEIPT_LIST_COLUMNS) {
			const fieldname = name.startsWith("receipt_") ? name : row(name);
			properties.push([fieldname, "in_list_view", 1], [fieldname, "columns", columns]);
		}
		const labels = {
			...SP_RECEIPT_ROW_LABELS,
			...Object.fromEntries(Object.entries(SP_ROW_SIDE_LABELS).map(([name, label]) => [row(name), label])),
			receipt_recipient_type: text.rows.receipt_recipient_type,
			receipt_recipient: text.rows.receipt_recipient,
			[row("account")]: text.rows.account,
		};
		for (const [fieldname, label] of Object.entries(labels)) {
			properties.push([fieldname, "label", label]);
		}
		for (const fieldname of ["receipt_recipient_type", row("account"), row("amount")]) {
			properties.push([fieldname, "reqd", 1]);
		}
		properties.push(
			["receipt_currency", "read_only", 1],
			[row("exchange_rate"), "hidden", 0],
			[row("exchange_rate"), "in_list_view", spReceiptConfig.isForeignPayer(doc) ? 1 : 0],
			[row("exchange_rate"), "columns", SP_RECEIPT_RATE_COLUMNS],
			[row("exchange_rate"), "read_only", 0],
			[row("exchange_rate"), "read_only_depends_on", spReceiptConfig.ROW_BASE_RATE],
			[row("company_amount"), "hidden", 0],
			[row("company_amount"), "read_only", 1],
		);
		for (const fieldname of spReceiptNumbers.GRID_FIELDS) {
			properties.push([fieldname, "formatter", spReceiptNumbers.formatter]);
		}
		return properties;
	},

	// Restores the DocType metadata for every property the Receipt or Payment
	// layout changes, so Transfer / Conversion keep their generic grid.
	genericGridProperties() {
		const changed = [spReceiptConfig.OPERATION, spReceiptConfig.PAYMENT].flatMap((operation_type) =>
			this.receiptGridProperties({ operation_type }),
		);
		const restored = changed.map(([fieldname, property]) => {
			const base = frappe.meta.docfield_map[spReceiptConfig.CHILD_DOCTYPE]?.[fieldname];
			return [fieldname, property, base ? base[property] ?? null : null];
		});
		const generic = [
			...SP_RECEIPT_GRID_FIELDS.map((fieldname) => [fieldname, "hidden", 1]),
			["receipt_payer_exchange_rate", "hidden", 1],
			["debit_exchange_rate", "in_list_view", 0],
			["debit_company_amount", "in_list_view", 0],
		];
		return [...restored, ...generic];
	},

	// Meta copies, grid.docfields, fields_map and every grid_row copy stay in
	// sync. Frappe Grid only shows !hidden && in_list_view columns.
	setGridProperty(frm, grid, fieldname, property, value) {
		let changed = false;
		const apply = (docfield) => {
			if (!docfield || (docfield[property] ?? null) === (value ?? null)) {
				return;
			}
			docfield[property] = value;
			changed = true;
		};
		const names = [frm.docname, ...(frm.doc[spReceiptConfig.TABLE] || []).map((row) => row.name)];
		for (const name of names) {
			apply(frappe.meta.get_docfield(grid.doctype, fieldname, name));
		}
		for (const docfield of grid.docfields || []) {
			if (docfield.fieldname === fieldname) {
				apply(docfield);
			}
		}
		apply(grid.fields_map?.[fieldname]);
		for (const gridRow of grid.grid_rows || []) {
			for (const docfield of gridRow.docfields || []) {
				if (docfield.fieldname === fieldname) {
					apply(docfield);
				}
			}
		}
		return changed;
	},

	// GridView column settings are stored per child DocType, but this child
	// table changes its columns with the operation type.
	ownColumns(grid) {
		if (spReceiptOwnedGrids.has(grid)) {
			return;
		}
		spReceiptOwnedGrids.add(grid);
		const setupUserDefinedColumns = grid.setup_user_defined_columns;
		grid.setup_user_defined_columns = function () {
			if (spReceiptConfig.isFlow(this.frm?.doc)) {
				this.user_defined_columns = [];
				return;
			}
			return setupUserDefinedColumns.call(this);
		};
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = spReceiptForm;
}
