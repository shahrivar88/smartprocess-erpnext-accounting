// Receipt form orchestration: one state object per document, grid layout per
// operation type, and the entry points called from the DocType form events.
const SP_RECEIPT_GRID_FIELDS = ["receipt_posting_date", "receipt_recipient_type", "receipt_recipient", "receipt_currency"];
const SP_RECEIPT_HIDDEN_FIELDS = [
	"debit_account_category", "debit_account", "debit_suggested_account", "debit_party_type",
	"debit_party", "debit_account_currency", "debit_amount", "debit_exchange_rate",
	"debit_company_amount", "debit_rate_direction", "debit_description", "credit_column",
	"credit_account_category", "credit_suggested_account", "credit_party_type", "credit_party",
	"credit_account_currency", "credit_rate_direction", "receipt_payer_exchange_rate",
];
// Column sizes only; the column order stays the Pair metadata order.
const SP_RECEIPT_LIST_COLUMNS = [
	["receipt_currency", 1],
	["receipt_recipient_type", 2],
	["receipt_recipient", 4],
	["credit_account", 3],
	["credit_amount", 2],
	["credit_exchange_rate", 2],
	["credit_company_amount", 2],
];
const SP_RECEIPT_ROW_LABELS = {
	receipt_currency: "ارز",
	credit_account: "معین پرداخت‌کننده",
	credit_amount: "مبلغ",
	credit_exchange_rate: "نرخ ارز",
	credit_company_amount: "مبلغ به ارز پایه",
	credit_description: "توضیح",
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
				preview: null,
				previewRequest: 0,
				previewTimer: null,
				quiet: 0,
				addingRow: false,
				currencyOptions: null,
				payerTypeDefault: null,
				payerTypeOptions: null,
				numberSettings: null,
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
		spReceiptHeader.setupQueries(frm);
		spReceiptRowQueries.setupQueries(frm);
	},

	async refresh(frm) {
		const isReceipt = spReceiptConfig.isReceipt(frm.doc);
		this.state(frm);
		spReceiptHeader.configure(frm, isReceipt);
		this.configureGrid(frm, isReceipt);
		if (!isReceipt) {
			frm.fields_dict.receipt_summary?.$wrapper.empty();
			return;
		}
		spReceiptValidation.installAddRowGuard(frm);
		spReceiptNumbers.install(frm);
		spReceiptRowQueries.installPayerTypeOrder(frm);
		await spReceiptHeader.initialize(frm);
		await spReceiptRowEvents.initializeRows(frm);
		spReceiptSummary.render(frm);
		spReceiptSummary.schedule(frm, 0);
	},

	validate(frm) {
		if (!spReceiptConfig.isReceipt(frm.doc)) {
			return;
		}
		return spReceiptValidation.validateSave(frm);
	},

	configureGrid(frm, isReceipt) {
		const field = frm.fields_dict[spReceiptConfig.TABLE];
		const grid = field?.grid;
		if (!grid) {
			return;
		}
		field.$wrapper.closest(".form-section").toggleClass("sp-receipt-layout-section", isReceipt);
		field.$wrapper.toggleClass("sp-receipt-wide-grid", isReceipt);
		frm.fields_dict.receipt_summary?.$wrapper.toggleClass("sp-receipt-wide-grid", isReceipt);
		this.ownColumns(grid);
		const properties = isReceipt ? this.receiptGridProperties() : this.genericGridProperties();
		const latest = new Map(properties.map(([fieldname, property, value]) => [`${fieldname}:${property}`, [fieldname, property, value]]));
		let changed = false;
		for (const [fieldname, property, value] of latest.values()) {
			changed = this.setGridProperty(frm, grid, fieldname, property, value) || changed;
		}
		if (changed) {
			grid.reset_grid();
		}
	},

	receiptGridProperties() {
		const properties = [];
		for (const fieldname of SP_RECEIPT_HIDDEN_FIELDS) {
			properties.push([fieldname, "hidden", 1]);
		}
		for (const fieldname of SP_RECEIPT_GRID_FIELDS) {
			properties.push([fieldname, "hidden", 0]);
		}
		for (const fieldname of ["receipt_posting_date", "credit_description"]) {
			properties.push([fieldname, "in_list_view", 0]);
		}
		for (const [fieldname, columns] of SP_RECEIPT_LIST_COLUMNS) {
			properties.push([fieldname, "in_list_view", 1], [fieldname, "columns", columns]);
		}
		for (const [fieldname, label] of Object.entries(SP_RECEIPT_ROW_LABELS)) {
			properties.push([fieldname, "label", label]);
		}
		for (const fieldname of ["receipt_currency", "receipt_recipient_type", "credit_account", "credit_amount"]) {
			properties.push([fieldname, "reqd", 1]);
		}
		properties.push(
			["credit_exchange_rate", "hidden", 0],
			["credit_exchange_rate", "read_only", 0],
			["credit_exchange_rate", "read_only_depends_on", spReceiptConfig.ROW_BASE_RATE],
			["credit_company_amount", "hidden", 0],
			["credit_company_amount", "read_only", 1],
		);
		for (const fieldname of spReceiptNumbers.GRID_FIELDS) {
			properties.push([fieldname, "formatter", spReceiptNumbers.formatter]);
		}
		return properties;
	},

	// Restores the DocType metadata for every property the Receipt layout
	// changes, so Payment / Transfer / Conversion keep their generic grid.
	genericGridProperties() {
		const restored = this.receiptGridProperties().map(([fieldname, property]) => {
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

	// The grid-level docfields (copied by new rows) and every existing row's
	// docfield copy get the same value, like frm.set_df_property for a row.
	setGridProperty(frm, grid, fieldname, property, value) {
		const names = [frm.docname, ...(frm.doc[spReceiptConfig.TABLE] || []).map((row) => row.name)];
		let changed = false;
		for (const name of names) {
			const docfield = frappe.meta.get_docfield(grid.doctype, fieldname, name);
			if (docfield && (docfield[property] ?? null) !== (value ?? null)) {
				docfield[property] = value;
				changed = true;
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
			if (spReceiptConfig.isReceipt(this.frm?.doc)) {
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
