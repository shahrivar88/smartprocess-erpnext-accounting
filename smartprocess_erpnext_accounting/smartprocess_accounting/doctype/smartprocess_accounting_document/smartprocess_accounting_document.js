const RECEIPT = "Receipt";
const ACCOUNT_RECIPIENT = "Account";
const PARTY_TYPES = ["Customer", "Supplier", "Employee", "SmartProcess Financial Intermediary"];
const RECEIPT_FIELDS = [
	"receipt_recipient_type",
	"receipt_recipient",
	"receipt_currency",
	"receipt_payer_exchange_rate",
];
const TECHNICAL_RECEIPT_FIELDS = [
	"debit_section",
	"debit_account_category",
	"debit_suggested_account",
	"debit_party_type",
	"debit_party",
	"debit_account_currency",
	"debit_rate_direction",
	"debit_description",
	"credit_column",
	"credit_account_category",
	"credit_account",
	"credit_suggested_account",
	"credit_party_type",
	"credit_party",
	"credit_account_currency",
	"credit_amount",
	"credit_exchange_rate",
	"credit_company_amount",
	"credit_rate_direction",
	"credit_description",
];

frappe.ui.form.on("SmartProcess Accounting Document", {
	refresh(frm) {
		if (canStartCorrection(frm)) {
			frm.add_custom_button(__("Correction"), () => promptForCorrection(frm));
		}
		receiptForm.configure(frm);
	},
	setup(frm) {
		frm.set_query("receipt_payer_type", () => ({ filters: { name: ["in", PARTY_TYPES] } }));
		frm.set_query("receipt_payer_account", () => ({
			filters: receiptAccountFilters(
				frm.doc.company,
				frm.doc.receipt_payer_currency,
				frm.doc.receipt_payer_type,
			),
		}));
		for (const side of ["debit", "credit"]) {
			frm.set_query(`${side}_account`, "operational_pairs", (doc, cdt, cdn) => {
				const row = locals[cdt][cdn];
				if (side === "debit" && frm.doc.operation_type === RECEIPT) {
					return {
						filters: receiptAccountFilters(
							frm.doc.company,
							row.receipt_currency,
							row.receipt_recipient_type,
						),
					};
				}
				const filters = { company: frm.doc.company, disabled: 0, is_group: 0 };
				const category = row[`${side}_account_category`];
				if (["Bank", "Cash", "Receivable", "Payable"].includes(category)) {
					filters.account_type = category;
				} else if (["Expense", "Income"].includes(category)) {
					filters.root_type = category;
				} else if (category === "Financial Intermediary") {
					filters.account_type = "Receivable";
				}
				return { filters };
			});
			frm.set_query(`${side}_party_type`, "operational_pairs", () => ({
				filters: { name: ["in", PARTY_TYPES] },
			}));
		}
	},
	operation_type(frm) {
		receiptForm.configure(frm);
	},
	async company(frm) {
		if (!frm.doc.company) {
			await frm.set_value("company_currency", "");
			if (frm.doc.operation_type === RECEIPT) {
				await frm.set_value("receipt_payer_account", "");
			}
			return;
		}
		const { message } = await frappe.call({
			method: "smartprocess_erpnext_accounting.smartprocess_accounting.v2_api.get_company_currency",
			args: { company: frm.doc.company },
		});
		await frm.set_value("company_currency", message || "");
		for (const row of frm.doc.operational_pairs || []) {
			await frappe.model.set_value(row.doctype, row.name, "company_currency", message || "");
			if (frm.doc.operation_type === RECEIPT) {
				await frappe.model.set_value(row.doctype, row.name, "debit_account", "");
			}
		}
		if (frm.doc.operation_type === RECEIPT) {
			await frm.set_value("receipt_payer_account", "");
			receiptForm.configure(frm);
		}
	},
	receipt_payer_type(frm) {
		return receiptForm.payerChanged(frm, true);
	},
	receipt_payer(frm) {
		return receiptForm.payerChanged(frm, true);
	},
	receipt_payer_currency(frm) {
		return receiptForm.payerCurrencyChanged(frm);
	},
	receipt_payer_account(frm) {
		return receiptForm.validatePayerAccount(frm);
	},
});

function receiptAccountFilters(company, currency, partyType) {
	const filters = { company, disabled: 0, is_group: 0, account_currency: currency };
	const accountType = receiptPartyAccountType(partyType);
	if (accountType) {
		filters.account_type = accountType;
	}
	return filters;
}

function receiptPartyAccountType(partyType) {
	if (partyType === "Customer" || partyType === "SmartProcess Financial Intermediary") {
		return "Receivable";
	}
	if (["Supplier", "Employee"].includes(partyType)) {
		return "Payable";
	}
	return null;
}

function updateGridProperty(grid, fieldname, property, value) {
	const docfield = grid.docfields?.find((field) => field.fieldname === fieldname);
	if (docfield) {
		docfield[property] = value;
	}
	if (grid.fields_map?.[fieldname]) {
		grid.fields_map[fieldname][property] = value;
	}
}

function renderGridProperties(grid, properties) {
	if (!grid.__sp_setup_fields) {
		// Grid.refresh rebuilds docfields. Reapply local labels without changing shared child metadata.
		const setupFields = grid.setup_fields;
		grid.setup_fields = function () {
			setupFields.call(this);
			for (const [fieldname, property, value] of this.__sp_properties || []) {
				updateGridProperty(this, fieldname, property, value);
			}
		};
		grid.__sp_setup_fields = true;
	}
	grid.__sp_properties = properties;
	grid.debounced_refresh?.cancel?.();
	grid.refresh();
}

const receiptForm = {
	configure(frm) {
		const isReceipt = frm.doc.operation_type === RECEIPT;
		this.configureHeader(frm, isReceipt);
		this.configureGrid(frm, isReceipt);
	},
	configureHeader(frm, isReceipt) {
		const labels = isReceipt
			? {
				operation_type: "نوع عملیات",
				company: "شرکت",
				posting_date: "تاریخ ثبت",
				general_reference: "مرجع عمومی",
				general_description: "شرح عمومی",
				pairs_section: "ردیف‌های دریافت",
				operational_pairs: "دریافت‌ها",
			}
			: {
				operation_type: "Operation Type",
				company: "Company",
				posting_date: "Posting Date",
				general_reference: "General Reference",
				general_description: "General Description",
				pairs_section: "Operational Pairs",
				operational_pairs: "Operational Pairs",
			};
		for (const [fieldname, label] of Object.entries(labels)) {
			frm.set_df_property(fieldname, "label", label);
		}
		for (const fieldname of [
			"receipt_payer_currency",
			"receipt_payer_account",
			"receipt_payer_type",
			"receipt_payer",
		]) {
			frm.toggle_display(fieldname, isReceipt);
			frm.toggle_reqd(fieldname, isReceipt);
		}
		frm.toggle_display("company_currency", !isReceipt);
	},
	configureGrid(frm, isReceipt) {
		const grid = frm.fields_dict.operational_pairs?.grid;
		if (!grid) {
			return;
		}
		for (const fieldname of RECEIPT_FIELDS) {
			grid.toggle_display(fieldname, isReceipt);
		}
		for (const fieldname of TECHNICAL_RECEIPT_FIELDS) {
			grid.toggle_display(fieldname, !isReceipt);
		}
		grid.set_column_disp_in_list_view(RECEIPT_FIELDS, isReceipt);
		grid.set_column_disp_in_list_view(TECHNICAL_RECEIPT_FIELDS, !isReceipt);
		grid.set_column_disp_in_list_view(["debit_account", "debit_amount"], true);
		if (!isReceipt) {
			grid.set_column_disp_in_list_view(["debit_exchange_rate", "debit_company_amount"], false);
			grid.toggle_display("debit_exchange_rate", true);
			grid.toggle_display("debit_company_amount", true);
			renderGridProperties(grid, [
				["receipt_recipient_type", "reqd", 0],
				["receipt_currency", "reqd", 0],
				["debit_account", "reqd", 0],
				["debit_amount", "reqd", 0],
				["debit_account", "label", "Account"],
				["debit_exchange_rate", "label", "Exchange Rate"],
				["debit_company_amount", "label", "Company Currency Amount"],
				["details_section", "label", "More Details"],
				["debit_account", "columns", 3],
				["debit_amount", "columns", 2],
				["debit_amount", "label", "Amount"],
			]);
			return;
		}

		const rows = frm.doc.operational_pairs || [];
		const currencies = new Set(rows.map((row) => row.receipt_currency).filter(Boolean));
		const hasForeign = rows.some(
			(row) => row.receipt_currency && row.receipt_currency !== frm.doc.company_currency,
		);
		const hasCrossCurrency = rows.some((row) => this.isCrossCurrency(frm, row));
		const hasPartyRecipient = rows.some(
			(row) => row.receipt_recipient_type !== ACCOUNT_RECIPIENT,
		);
		grid.toggle_display(
			"receipt_recipient",
			hasPartyRecipient,
		);
		grid.toggle_display("debit_exchange_rate", hasForeign);
		grid.toggle_display("debit_company_amount", hasForeign);
		grid.toggle_display("receipt_payer_exchange_rate", hasCrossCurrency);
		grid.set_column_disp_in_list_view("receipt_recipient", hasPartyRecipient);
		grid.set_column_disp_in_list_view("debit_exchange_rate", hasForeign);
		grid.set_column_disp_in_list_view("debit_company_amount", hasForeign);
		grid.set_column_disp_in_list_view("receipt_payer_exchange_rate", hasCrossCurrency);
		renderGridProperties(grid, [
			["receipt_recipient_type", "reqd", 1],
			["receipt_currency", "reqd", 1],
			["debit_account", "reqd", 1],
			["debit_amount", "reqd", 1],
			["debit_account", "label", "معین دریافتی"],
			["debit_exchange_rate", "label", "نرخ"],
			["debit_company_amount", "label", "مبلغ ارز پایه"],
			["details_section", "label", "جزئیات بیشتر"],
			["debit_exchange_rate", "columns", 1],
			["debit_company_amount", "columns", hasCrossCurrency ? 1 : 2],
			["debit_account", "columns", 2],
			["debit_amount", "columns", 1],
			[
				"debit_amount",
				"label",
				currencies.size > 1 ? __("مبلغ / مبلغ ارز") : hasForeign ? __("مبلغ ارز") : __("مبلغ"),
			],
		]);
		for (const row of rows) {
			if (row.__sp_previous_receipt_currency === undefined) {
				row.__sp_previous_receipt_currency = row.receipt_currency || "";
			}
			this.configureGridRow(frm, row);
		}
	},
	configureGridRow(frm, row) {
		const grid = frm.fields_dict.operational_pairs?.grid;
		const gridRow = grid?.grid_rows_by_docname?.[row.name];
		if (!gridRow) {
			return;
		}
		const foreign = row.receipt_currency && row.receipt_currency !== frm.doc.company_currency;
		gridRow.toggle_display("receipt_recipient", row.receipt_recipient_type !== ACCOUNT_RECIPIENT);
		gridRow.toggle_display("debit_exchange_rate", Boolean(foreign));
		gridRow.toggle_display("debit_company_amount", Boolean(foreign));
		gridRow.toggle_display("receipt_payer_exchange_rate", this.isCrossCurrency(frm, row));
	},
	isCrossCurrency(frm, row) {
		return Boolean(
			frm.doc.receipt_payer_currency
			&& frm.doc.receipt_payer_currency !== frm.doc.company_currency
			&& row.receipt_currency
			&& frm.doc.receipt_payer_currency !== row.receipt_currency,
		);
	},
	async payerChanged(frm, clearAccount) {
		if (frm.doc.operation_type !== RECEIPT) {
			return;
		}
		if (clearAccount && frm.doc.receipt_payer_account) {
			await frm.set_value("receipt_payer_account", "");
		}
		await this.suggestPayerAccount(frm);
	},
	async payerCurrencyChanged(frm) {
		if (frm.doc.operation_type !== RECEIPT) {
			return;
		}
		await this.clearMismatchedPayerAccount(frm);
		for (const row of frm.doc.operational_pairs || []) {
			await frappe.model.set_value(row.doctype, row.name, "receipt_payer_exchange_rate", "");
		}
		await this.suggestPayerAccount(frm);
		this.configureGrid(frm, true);
	},
	async validatePayerAccount(frm) {
		if (frm.doc.operation_type !== RECEIPT || !frm.doc.receipt_payer_account) {
			return;
		}
		const details = await getAccountDetails(frm.doc.receipt_payer_account, frm.doc.company);
		if (details.account_currency !== frm.doc.receipt_payer_currency) {
			await frm.set_value("receipt_payer_account", "");
			frappe.msgprint(__("ارز معین پرداخت‌کننده با ارز پرداخت‌کننده یکسان نیست."));
		}
	},
	async clearMismatchedPayerAccount(frm) {
		if (!frm.doc.receipt_payer_account || !frm.doc.company) {
			return;
		}
		const details = await getAccountDetails(frm.doc.receipt_payer_account, frm.doc.company);
		if (details.account_currency !== frm.doc.receipt_payer_currency) {
			await frm.set_value("receipt_payer_account", "");
		}
	},
	async suggestPayerAccount(frm) {
		if (
			frm.doc.receipt_payer_account
			|| !frm.doc.receipt_payer_type
			|| !frm.doc.receipt_payer
			|| !frm.doc.company
			|| !frm.doc.receipt_payer_currency
		) {
			return;
		}
		const account = await getReceiptSuggestion(
			frm.doc.receipt_payer_type,
			frm.doc.receipt_payer,
			frm.doc.company,
			frm.doc.receipt_payer_currency,
		);
		if (account && !frm.doc.receipt_payer_account) {
			await frm.set_value("receipt_payer_account", account);
		}
	},
};

function canStartCorrection(frm) {
	const hasPermission = (permissionType) =>
		(frm.perm || []).some((permission) => Boolean(permission[permissionType]));
	return frm.doc.docstatus === 1
		&& ["read", "write", "cancel", "amend", "create"].every(hasPermission);
}

function promptForCorrection(frm) {
	frappe.prompt(
		[
			{
				fieldname: "correction_reason",
				fieldtype: "Small Text",
				label: __("Correction Reason"),
				reqd: 1,
			},
		],
		(values) => startCorrection(frm, values.correction_reason),
		__("Correction"),
		__("Create Draft"),
	);
}

function startCorrection(frm, correctionReason) {
	return frm.call({
		method: "start_correction",
		args: { correction_reason: correctionReason },
		freeze: true,
		freeze_message: __("Creating correction Draft..."),
		callback({ message }) {
			if (message?.doctype && message?.name) {
				frappe.set_route("Form", message.doctype, message.name);
			}
		},
	});
}

async function getAccountDetails(account, company) {
	const { message } = await frappe.call({
		method: "smartprocess_erpnext_accounting.smartprocess_accounting.v2_api.get_account_details",
		args: { account, company },
	});
	return message;
}

async function getReceiptSuggestion(partyType, party, company, currency) {
	const { message } = await frappe.call({
		method: "smartprocess_erpnext_accounting.smartprocess_accounting.v2_api.get_receipt_party_account_suggestion",
		args: { party_type: partyType, party, company, currency },
	});
	return message || "";
}

const spAccountingPair = {
	async refresh_account(frm, cdt, cdn, side) {
		const row = locals[cdt][cdn];
		const account = row[`${side}_account`];
		if (!account || !frm.doc.company) {
			return;
		}
		if (frm.doc.operation_type === RECEIPT && side === "debit") {
			return this.refreshReceiptAccount(frm, cdt, cdn);
		}
		const message = await getAccountDetails(account, frm.doc.company);
		await frappe.model.set_value(cdt, cdn, `${side}_account_currency`, message.account_currency);
		await frappe.model.set_value(cdt, cdn, "company_currency", frm.doc.company_currency);
		if (message.account_currency === frm.doc.company_currency) {
			await frappe.model.set_value(cdt, cdn, `${side}_exchange_rate`, 1);
		}
		await this.calculate(frm, cdt, cdn, side);
		await this.suggest(frm, cdt, cdn, side);
	},
	async refreshReceiptAccount(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.debit_account) {
			return;
		}
		const details = await getAccountDetails(row.debit_account, frm.doc.company);
		if (details.account_currency !== row.receipt_currency) {
			await frappe.model.set_value(cdt, cdn, "debit_account", "");
			frappe.msgprint(__("ارز معین دریافتی با ارز ردیف یکسان نیست."));
			return;
		}
		await frappe.model.set_value(cdt, cdn, "debit_account_currency", details.account_currency);
		await frappe.model.set_value(cdt, cdn, "company_currency", frm.doc.company_currency);
		await this.calculate(frm, cdt, cdn, "debit");
	},
	async calculate(frm, cdt, cdn, side) {
		const row = locals[cdt][cdn];
		if (row.__sp_calculating) {
			return;
		}
		row.__sp_calculating = true;
		try {
			const accountCurrency = frm.doc.operation_type === RECEIPT && side === "debit"
				? row.receipt_currency
				: row[`${side}_account_currency`];
			let rate = Number(row[`${side}_exchange_rate`] || 0);
			if (accountCurrency && accountCurrency === frm.doc.company_currency) {
				rate = 1;
				await frappe.model.set_value(cdt, cdn, `${side}_exchange_rate`, 1);
			}
			const amount = Number(row[`${side}_amount`] || 0);
			await frappe.model.set_value(cdt, cdn, `${side}_company_amount`, amount * rate);
			const meaning = accountCurrency && frm.doc.company_currency && rate > 0
				? `1 ${accountCurrency} = ${rate} ${frm.doc.company_currency}`
				: "";
			await frappe.model.set_value(cdt, cdn, `${side}_rate_direction`, meaning);
		} finally {
			row.__sp_calculating = false;
		}
	},
	async suggest(frm, cdt, cdn, side) {
		const row = locals[cdt][cdn];
		const partyType = row[`${side}_party_type`];
		const party = row[`${side}_party`];
		const currency = row[`${side}_account_currency`];
		if (!partyType || !party || !frm.doc.company || !currency) {
			return frappe.model.set_value(cdt, cdn, `${side}_suggested_account`, "");
		}
		const { message } = await frappe.call({
			method: "smartprocess_erpnext_accounting.smartprocess_accounting.v2_api.get_party_account_suggestion",
			args: { party_type: partyType, party, company: frm.doc.company, currency },
		});
		return frappe.model.set_value(cdt, cdn, `${side}_suggested_account`, message || "");
	},
	async receiptRecipientChanged(frm, cdt, cdn, clearAccount) {
		if (frm.doc.operation_type !== RECEIPT) {
			return;
		}
		const row = locals[cdt][cdn];
		if (row.receipt_recipient_type === ACCOUNT_RECIPIENT) {
			await frappe.model.set_value(cdt, cdn, "receipt_recipient", "");
		}
		if (clearAccount && row.debit_account) {
			await frappe.model.set_value(cdt, cdn, "debit_account", "");
		}
		await this.suggestReceiptAccount(frm, cdt, cdn);
		receiptForm.configureGrid(frm, true);
	},
	async receiptCurrencyChanged(frm, cdt, cdn) {
		if (frm.doc.operation_type !== RECEIPT) {
			return;
		}
		const row = locals[cdt][cdn];
		const changed = row.__sp_previous_receipt_currency !== undefined
			&& row.__sp_previous_receipt_currency !== row.receipt_currency;
		row.__sp_previous_receipt_currency = row.receipt_currency || "";
		await frappe.model.set_value(cdt, cdn, "debit_account_currency", row.receipt_currency || "");
		if (changed && !row.__sp_receipt_copying) {
			await frappe.model.set_value(cdt, cdn, "debit_exchange_rate", "");
			await frappe.model.set_value(cdt, cdn, "receipt_payer_exchange_rate", "");
		}
		if (row.receipt_currency === frm.doc.company_currency) {
			await frappe.model.set_value(cdt, cdn, "debit_exchange_rate", 1);
		}
		if (row.debit_account) {
			const details = await getAccountDetails(row.debit_account, frm.doc.company);
			if (details.account_currency !== row.receipt_currency) {
				await frappe.model.set_value(cdt, cdn, "debit_account", "");
			}
		}
		await this.suggestReceiptAccount(frm, cdt, cdn);
		await this.calculate(frm, cdt, cdn, "debit");
		receiptForm.configureGrid(frm, true);
	},
	async suggestReceiptAccount(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (
			row.debit_account
			|| row.receipt_recipient_type === ACCOUNT_RECIPIENT
			|| !row.receipt_recipient_type
			|| !row.receipt_recipient
			|| !row.receipt_currency
			|| !frm.doc.company
		) {
			return;
		}
		const account = await getReceiptSuggestion(
			row.receipt_recipient_type,
			row.receipt_recipient,
			frm.doc.company,
			row.receipt_currency,
		);
		if (account && !row.debit_account) {
			await frappe.model.set_value(cdt, cdn, "debit_account", account);
		}
	},
	async copyPreviousReceiptRow(frm, cdt, cdn) {
		if (frm.doc.operation_type !== RECEIPT) {
			return;
		}
		const rows = frm.doc.operational_pairs || [];
		const index = rows.findIndex((candidate) => candidate.name === cdn);
		if (index < 1) {
			receiptForm.configureGrid(frm, true);
			return;
		}
		const row = locals[cdt][cdn];
		const previous = rows[index - 1];
		row.__sp_receipt_copying = true;
		try {
			for (const fieldname of [
				"receipt_recipient_type",
				"receipt_recipient",
				"receipt_currency",
				"debit_account",
				"debit_exchange_rate",
				"receipt_payer_exchange_rate",
			]) {
				await frappe.model.set_value(cdt, cdn, fieldname, previous[fieldname] || "");
			}
			for (const fieldname of ["debit_amount", "debit_company_amount", "credit_amount", "credit_company_amount"]) {
				await frappe.model.set_value(cdt, cdn, fieldname, "");
			}
		} finally {
			row.__sp_receipt_copying = false;
		}
		receiptForm.configureGrid(frm, true);
	},
};

const events = {
	form_render(frm, cdt, cdn) {
		if (frm.doc.operation_type === RECEIPT) {
			receiptForm.configureGridRow(frm, locals[cdt][cdn]);
		}
	},
	operational_pairs_add(frm, cdt, cdn) {
		return spAccountingPair.copyPreviousReceiptRow(frm, cdt, cdn);
	},
	receipt_recipient_type(frm, cdt, cdn) {
		return spAccountingPair.receiptRecipientChanged(frm, cdt, cdn, true);
	},
	receipt_recipient(frm, cdt, cdn) {
		return spAccountingPair.receiptRecipientChanged(frm, cdt, cdn, true);
	},
	receipt_currency(frm, cdt, cdn) {
		return spAccountingPair.receiptCurrencyChanged(frm, cdt, cdn);
	},
};
for (const side of ["debit", "credit"]) {
	events[`${side}_account`] = (frm, cdt, cdn) => spAccountingPair.refresh_account(frm, cdt, cdn, side);
	events[`${side}_amount`] = (frm, cdt, cdn) => spAccountingPair.calculate(frm, cdt, cdn, side);
	events[`${side}_exchange_rate`] = (frm, cdt, cdn) => spAccountingPair.calculate(frm, cdt, cdn, side);
	events[`${side}_party_type`] = (frm, cdt, cdn) => spAccountingPair.suggest(frm, cdt, cdn, side);
	events[`${side}_party`] = (frm, cdt, cdn) => spAccountingPair.suggest(frm, cdt, cdn, side);
}
frappe.ui.form.on("SmartProcess Accounting Pair", events);
