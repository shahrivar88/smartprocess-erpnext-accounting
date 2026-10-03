const RECEIPT = "Receipt";
const ACCOUNT_RECIPIENT = "Account";
// ERPNext-native bank entity for Receipt rows: the Link type value is the Bank Account doctype,
// so the row entity field selects company Bank Account records while the ledger Account stays separate.
const BANK_ACCOUNT_RECIPIENT = "Bank Account";
const PARTY_TYPES = ["Customer", "Supplier", "Employee", "SmartProcess Financial Intermediary"];
const RECEIVER_ACCOUNT_TYPES = {
	"بانک": "Bank",
	"صندوق": "Cash",
	"سایر حساب‌ها": null,
};
// Display labels only — the stored values stay the native Party Type names
// (receipt_payer_type links by DocType). Options order comes from the field metadata.
const RECEIVER_KIND_LABELS = {
	Customer: "مشتری",
	Supplier: "تامین‌کننده",
	"SmartProcess Financial Intermediary": "واسطه مالی",
	Employee: "کارمند",
};
const RECEIPT_RECIPIENT_TYPES = [...PARTY_TYPES, BANK_ACCOUNT_RECIPIENT, ACCOUNT_RECIPIENT];
const RECEIPT_FIELDS = [
	"receipt_posting_date",
	"receipt_recipient_type",
	"receipt_recipient",
	"receipt_currency",
];
const TECHNICAL_RECEIPT_FIELDS = [
	"debit_account_category",
	"debit_account",
	"debit_suggested_account",
	"debit_party_type",
	"debit_party",
	"debit_account_currency",
	"debit_amount",
	"debit_exchange_rate",
	"debit_company_amount",
	"debit_rate_direction",
	"debit_description",
	"credit_column",
	"credit_account_category",
	"credit_suggested_account",
	"credit_party_type",
	"credit_party",
	"credit_account_currency",
];
const RECEIPT_NUMBER_FIELDS = ["credit_amount", "credit_exchange_rate", "credit_company_amount"];

function numberFormatForField(df, doc) {
	const currency = df.fieldtype === "Currency"
		? frappe.meta.get_field_currency(df, doc)
		: null;
	return get_number_format(currency);
}

function compactFormattedValue(formattedValue, df, doc) {
	const numeric = window.smartprocessAccounting?.numeric;
	if (!numeric) {
		return formattedValue;
	}
	const format = numberFormatForField(df, doc);
	const decimalSeparator = get_number_format_info(format).decimal_str;
	return numeric.compactFormattedNumber(formattedValue, decimalSeparator);
}

function compactNumberFormatter(value, df, options, doc) {
	const standardField = { ...df, formatter: null };
	const formatter = frappe.form.get_formatter(df.fieldtype);
	const formatted = formatter(
		value,
		standardField,
		{ ...(options || {}), inline: true, only_value: true },
		doc,
	);
	return compactFormattedValue(formatted, standardField, doc);
}

function formatReceiptSummaryValue(value) {
	return compactNumberFormatter(
		value,
		{ fieldtype: "Float", precision: 9 },
		{ inline: true, only_value: true },
		{},
	);
}

function receiverTotalMarkup() {
	return `<div class="sp-receipt-receiver-total">
		<div class="sp-receipt-receiver-title">مجموع واریزی به دریافت‌کننده</div>
		<div class="sp-receipt-receiver-values text-muted">—</div>
	</div>`;
}

function receiverTotalLine(message) {
	const receiver = message.party ? `${message.account} · ${message.party}` : message.account;
	return [
		`<span class="sp-receipt-receiver-name">${frappe.utils.escape_html(receiver)}</span>`,
		`<span class="sp-receipt-receiver-amount">${frappe.utils.escape_html(message.currency)} ${formatReceiptSummaryValue(Number(message.amount))}</span>`,
		`<span class="sp-receipt-receiver-base">معادل ${formatReceiptSummaryValue(Number(message.company_amount))} ${frappe.utils.escape_html(message.company_currency)}</span>`,
	].join(" | ");
}

// A blank auto-created grid row is not user input: live logic ignores it until the
// user enters a meaningful value. Save/Submit validation stays strict server-side.
function isRowMeaningfullyStarted(row) {
	return Boolean(
		row?.receipt_recipient_type
		|| row?.receipt_recipient
		|| row?.receipt_currency
		|| row?.credit_account
		|| row?.credit_amount
		|| row?.credit_exchange_rate,
	);
}

// The receiver-total display runs full server canonicalization, so it must stay quiet
// until the user has actually started entering the first child row.
function canCalculateLiveReceiptSummary(frm) {
	return Boolean(
		frm.doc.company
		&& frm.doc.receipt_receiver_kind
		&& frm.doc.receipt_payer_account
		&& frm.doc.receipt_payer_currency
	) && (frm.doc.operational_pairs || []).some(isRowMeaningfullyStarted);
}

function receiptReceiverTotalPayload(frm) {
	return {
		doctype: frm.doc.doctype,
		name: frm.doc.name,
		operation_type: frm.doc.operation_type,
		company: frm.doc.company,
		posting_date: frm.doc.posting_date,
		receipt_receiver_kind: frm.doc.receipt_receiver_kind,
		receipt_payer_type: frm.doc.receipt_payer_type,
		receipt_payer: frm.doc.receipt_payer,
		receipt_payer_currency: frm.doc.receipt_payer_currency,
		receipt_payer_exchange_rate: frm.doc.receipt_payer_exchange_rate,
		receipt_payer_account: frm.doc.receipt_payer_account,
		operational_pairs: (frm.doc.operational_pairs || []).map((row) => ({
			doctype: row.doctype,
			name: row.name,
			receipt_posting_date: row.receipt_posting_date,
			receipt_recipient_type: row.receipt_recipient_type,
			receipt_recipient: row.receipt_recipient,
			receipt_currency: row.receipt_currency,
			credit_account: row.credit_account,
			credit_amount: row.credit_amount,
			credit_exchange_rate: row.credit_exchange_rate,
			credit_description: row.credit_description,
		})),
	};
}

function receiptCompactNumberFormatter(value, df, options, doc) {
	const parent = doc?.parenttype && doc?.parent
		? locals[doc.parenttype]?.[doc.parent]
		: doc;
	const standardField = { ...df, formatter: null };
	if (parent?.operation_type !== RECEIPT) {
		return frappe.form.get_formatter(df.fieldtype)(value, standardField, options, doc);
	}
	return compactNumberFormatter(value, standardField, options, doc);
}

function installReceiptRowStaticNumberFormatters(grid) {
	for (const row of grid.frm?.doc?.operational_pairs || []) {
		for (const fieldname of RECEIPT_NUMBER_FIELDS) {
			frappe.meta.set_formatter(
				"SmartProcess Accounting Pair",
				fieldname,
				row.name,
				receiptCompactNumberFormatter,
			);
		}
	}
}

function configureCompactNumberInput(control) {
	if (!control?.format_for_input || !["Currency", "Float"].includes(control.df?.fieldtype)) {
		return;
	}
	if (!control.__sp_original_format_for_input) {
		control.__sp_original_format_for_input = control.format_for_input;
		control.format_for_input = function (value) {
			const formatted = this.__sp_original_format_for_input.call(this, value);
			return compactFormattedValue(formatted, this.df, this.doc || this.frm?.doc);
		};
	}
	if (control.$input && document.activeElement !== control.$input.get(0)) {
		control.set_formatted_input(control.value);
	}
}

frappe.ui.form.on("SmartProcess Accounting Document", {
	refresh(frm) {
		// Posting units must cancel only through the Receipt's authorized path; keep
		// frappe's linked-docs auto-cancel from cancelling them directly.
		frm.ignore_doctypes_on_cancel_all = ["SmartProcess Accounting Posting"];
		if (canStartCorrection(frm)) {
			frm.add_custom_button(__("Correction"), () => promptForCorrection(frm));
		}
		receiptForm.configure(frm);
		void receiptForm.initialize(frm);
	},
	setup(frm) {
		frm.set_query("receipt_recipient_type", "operational_pairs", () => ({
			filters: { name: ["in", RECEIPT_RECIPIENT_TYPES] },
		}));
		frm.set_query("receipt_payer_account", () => ({
			filters: receiptAccountFilters(
				frm.doc.company,
				frm.doc.receipt_payer_currency,
				frm.doc.receipt_payer_type,
				frm.doc.receipt_receiver_kind,
			),
		}));
		frm.set_query("receipt_bank_account", () => ({
			query: "smartprocess_erpnext_accounting.smartprocess_accounting.v2_api.bank_account_query",
			filters: { company: frm.doc.company, currency: frm.doc.receipt_payer_currency },
		}));
		// Currency is the first Receipt choice: the Party list is filtered by the
		// selected currency using the single-currency Party rule server-side.
		frm.set_query("receipt_payer", () => {
			if (frm.doc.operation_type !== RECEIPT) {
				return {};
			}
			return {
				query: "smartprocess_erpnext_accounting.smartprocess_accounting.v2_api.party_currency_query",
				filters: {
					party_type: frm.doc.receipt_payer_type,
					company: frm.doc.company,
					currency: frm.doc.receipt_payer_currency,
				},
			};
		});
		frm.set_query("receipt_recipient", "operational_pairs", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			if (frm.doc.operation_type !== RECEIPT) {
				return {};
			}
			if (row?.receipt_recipient_type === BANK_ACCOUNT_RECIPIENT) {
				return {
					query: "smartprocess_erpnext_accounting.smartprocess_accounting.v2_api.bank_account_query",
					filters: { company: frm.doc.company, currency: row.receipt_currency },
				};
			}
			if (PARTY_TYPES.includes(row?.receipt_recipient_type)) {
				return {
					query: "smartprocess_erpnext_accounting.smartprocess_accounting.v2_api.party_currency_query",
					filters: {
						party_type: row.receipt_recipient_type,
						company: frm.doc.company,
						currency: row.receipt_currency,
					},
				};
			}
			if (row?.receipt_recipient_type === ACCOUNT_RECIPIENT) {
				return {
					filters: {
						company: frm.doc.company,
						disabled: 0,
						is_group: 0,
						account_currency: row.receipt_currency,
						account_type: ["not in", ["Receivable", "Payable"]],
					},
				};
			}
			return {};
		});
		for (const side of ["debit", "credit"]) {
			frm.set_query(`${side}_account`, "operational_pairs", (doc, cdt, cdn) => {
				const row = locals[cdt][cdn];
				if (side === "credit" && frm.doc.operation_type === RECEIPT) {
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
		return receiptForm.initialize(frm);
	},
	posting_date(frm) {
		return receiptForm.parentPostingDateChanged(frm);
	},
	async company(frm) {
		if (!frm.doc.company) {
			await frm.set_value("company_currency", "");
			if (frm.doc.operation_type === RECEIPT) {
				await frm.set_value("receipt_payer_account", "");
				await frm.set_value("receipt_bank_account", "");
			}
			receiptForm.applyCurrencyOptions(frm, []);
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
				await frappe.model.set_value(row.doctype, row.name, "credit_account", "");
			}
		}
		if (frm.doc.operation_type === RECEIPT) {
			await frm.set_value("receipt_payer_account", "");
			await frm.set_value("receipt_bank_account", "");
			await receiptForm.loadCurrencyOptions(frm, true);
			const previousCurrency = frm.doc.receipt_payer_currency;
			await receiptForm.defaultReceiverCurrency(frm, message || "");
			if (!previousCurrency || previousCurrency === frm.doc.receipt_payer_currency) {
				await receiptForm.applyReceiverCurrency(frm);
			}
		}
	},
	receipt_receiver_kind(frm) {
		return receiptForm.headerTypeChanged(frm);
	},
	receipt_payer(frm) {
		return receiptForm.headerPartyChanged(frm);
	},
	receipt_payer_currency(frm) {
		return receiptForm.headerCurrencyChanged(frm);
	},
	receipt_payer_exchange_rate(frm) {
		return receiptForm.payerRateChanged(frm);
	},
	receipt_payer_account(frm) {
		return receiptForm.headerAccountChanged(frm);
	},
	receipt_bank_account(frm) {
		return receiptForm.headerBankChanged(frm);
	},
});

function receiptAccountFilters(company, currency, partyType, receiverKind = null) {
	const filters = { company, disabled: 0, is_group: 0, account_currency: currency };
	if (partyType === BANK_ACCOUNT_RECIPIENT) {
		filters.account_type = "Bank";
		return filters;
	}
	if (partyType === ACCOUNT_RECIPIENT) {
		filters.account_type = ["not in", ["Receivable", "Payable"]];
		return filters;
	}
	if (receiverKind === "بانک" || receiverKind === "صندوق") {
		filters.account_type = RECEIVER_ACCOUNT_TYPES[receiverKind];
		return filters;
	}
	if (receiverKind === "سایر حساب‌ها") {
		filters.account_type = ["not in", ["Bank", "Cash", "Receivable", "Payable"]];
		return filters;
	}
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

function configureReceiptGridRowLifecycle(gridRow) {
	if (!gridRow.__sp_make_control) {
		const makeControl = gridRow.make_control;
		gridRow.make_control = function (column) {
			makeControl.call(this, column);
			if (RECEIPT_NUMBER_FIELDS.includes(column.df.fieldname)) {
				configureCompactNumberInput(column.field);
			}
		};
		gridRow.__sp_make_control = true;
	}
	for (const fieldname of RECEIPT_NUMBER_FIELDS) {
		configureCompactNumberInput(gridRow.on_grid_fields_dict?.[fieldname]);
		configureCompactNumberInput(gridRow.grid_form?.fields_dict?.[fieldname]);
	}
}

function installReceiptGridLifecycle(grid) {
	if (grid.__sp_lifecycle_installed) {
		return;
	}
	const setupFields = grid.setup_fields;
	grid.setup_fields = function () {
		setupFields.call(this);
		for (const [fieldname, property, value] of this.__sp_properties || []) {
			updateGridProperty(this, fieldname, property, value);
		}
		if (this.__sp_receipt_currency_options !== undefined) {
			updateGridProperty(this, "receipt_currency", "options", this.__sp_receipt_currency_options);
		}
	};
	const setupUserDefinedColumns = grid.setup_user_defined_columns;
	grid.setup_user_defined_columns = function () {
		setupUserDefinedColumns.call(this);
		if (!this.__sp_receipt_active) {
			return;
		}
		this.user_defined_columns = (this.__sp_receipt_columns || [])
			.map(([fieldname, columns]) => {
				const field = this.docfields.find((candidate) => candidate.fieldname === fieldname);
				if (!field) {
					return null;
				}
				field.in_list_view = 1;
				field.columns = columns;
				return field;
			})
			.filter(Boolean);
	};
	const refresh = grid.refresh;
	grid.refresh = function () {
		if (this.__sp_receipt_active) {
			installReceiptRowStaticNumberFormatters(this);
		}
		refresh.call(this);
		if (this.__sp_receipt_active) {
			for (const gridRow of this.grid_rows || []) {
				configureReceiptGridRowLifecycle(gridRow);
			}
		}
	};
	grid.__sp_lifecycle_installed = true;
}

function receiptGridColumns(hasPartyRecipient, hasForeign) {
	// Colsizes map to frappe's fixed-px ladder (1:60 2:100 3:140 4:200 5:250 …)
	// as a sensible fallback; the designed proportions are enforced by the
	// proportional flex rules in public/css/receipt_form.css. All states keep
	// the total above 10 on purpose so frappe's redistribution loop does not
	// inflate these values.
	// Row cascade order is Currency → Type → Entity → Account → Amount/Rate.
	const columns = [
		["receipt_currency", 1],
		["receipt_recipient_type", 2],
	];
	if (hasPartyRecipient) {
		columns.push(["receipt_recipient", 5]);
	}
	columns.push(
		["credit_account", hasPartyRecipient ? 4 : 5],
		["credit_amount", 2],
	);
	if (hasForeign) {
		columns.push(["credit_exchange_rate", 2], ["credit_company_amount", 3]);
	}
	return columns;
}

function renderGridProperties(grid, properties, receiptColumns = null) {
	installReceiptGridLifecycle(grid);
	grid.__sp_properties = properties;
	grid.__sp_receipt_active = Boolean(receiptColumns);
	grid.__sp_receipt_columns = receiptColumns || [];
	grid.debounced_refresh?.cancel?.();
	grid.refresh();
}

const receiptForm = {
	configure(frm) {
		const isReceipt = frm.doc.operation_type === RECEIPT;
		if (isReceipt && !frm.doc.receipt_receiver_kind && frm.doc.receipt_payer_type) {
			frm.doc.receipt_receiver_kind = frm.doc.receipt_payer_type;
			frm.refresh_field("receipt_receiver_kind");
		}
		this.configureHeader(frm, isReceipt);
		this.configureGrid(frm, isReceipt);
		if (isReceipt && frm.__sp_previous_payer_currency === undefined) {
			frm.__sp_previous_payer_currency = frm.doc.receipt_payer_currency || "";
			frm.__sp_receiver_currency_explicit = !frm.is_new()
				&& Boolean(frm.doc.receipt_payer_currency);
		}
	},
	async initialize(frm) {
		if (frm.doc.operation_type !== RECEIPT) {
			return;
		}
		await this.initializeReceiverType(frm);
		await this.loadCurrencyOptions(frm);
		await this.defaultReceiverCurrency(frm, frm.doc.company_currency || "");
		if (frm.doc.docstatus === 0 && frm.doc.receipt_payer) {
			await this.syncReceiverCurrencyFromParty(frm);
		}
	},
	async initializeReceiverType(frm) {
		const receiverKind = frm.doc.receipt_receiver_kind || "Customer";
		if (frm.doc.receipt_receiver_kind !== receiverKind) {
			await frm.set_value("receipt_receiver_kind", receiverKind);
		}
		const partyType = PARTY_TYPES.includes(receiverKind) ? receiverKind : "";
		if (frm.doc.receipt_payer_type !== partyType) {
			await frm.set_value("receipt_payer_type", partyType);
		}
		frm.refresh_field("receipt_payer");
		this.configureHeader(frm, true);
	},
	async defaultReceiverCurrency(frm, companyCurrency) {
		if (!companyCurrency) {
			return;
		}
		const currentCurrency = frm.doc.receipt_payer_currency || "";
		const currentIsValid = (frm.__sp_currency_options || []).includes(currentCurrency);
		if (frm.__sp_receiver_currency_explicit && currentIsValid) {
			return;
		}
		frm.__sp_setting_receiver_currency = true;
		try {
			if (currentCurrency !== companyCurrency) {
				await frm.set_value("receipt_payer_currency", companyCurrency);
			}
			frm.__sp_receiver_currency_explicit = false;
		} finally {
			frm.__sp_setting_receiver_currency = false;
		}
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
				operational_pairs: "پرداخت‌کنندگان / منابع",
				receipt_payer_type: "نوع دریافت‌کننده",
				receipt_payer: "دریافت‌کننده",
				receipt_payer_currency: "ارز دریافت‌کننده",
				receipt_payer_exchange_rate: "نرخ ارز دریافت‌کننده",
				receipt_payer_account: "معین دریافت‌کننده",
				receipt_bank_account: "دریافت‌کننده",
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
		this.applyReceiverKindLabels(frm);
		for (const fieldname of ["receipt_receiver_kind", "receipt_payer_currency"]) {
			frm.toggle_display(fieldname, isReceipt);
			frm.toggle_reqd(fieldname, isReceipt);
		}
		const bankReceiver = isReceipt && frm.doc.receipt_receiver_kind === "بانک";
		frm.toggle_display("receipt_bank_account", bankReceiver);
		frm.toggle_reqd("receipt_bank_account", bankReceiver);
		// The ledger Account stays a separate, always-visible Receipt receiver field.
		frm.toggle_display("receipt_payer_account", isReceipt);
		frm.toggle_reqd("receipt_payer_account", isReceipt);
		const partyReceiver = isReceipt && PARTY_TYPES.includes(frm.doc.receipt_receiver_kind);
		frm.toggle_display("receipt_payer_type", false);
		frm.toggle_reqd("receipt_payer_type", false);
		frm.toggle_display("receipt_payer", partyReceiver);
		frm.toggle_reqd("receipt_payer", partyReceiver);
		frm.set_df_property(
			"supplementary_section",
			"label",
			isReceipt ? "اطلاعات تکمیلی" : "Additional Information",
		);
		const foreignPayer = isReceipt
			&& frm.doc.receipt_payer_currency
			&& frm.doc.receipt_payer_currency !== frm.doc.company_currency;
		// Rate visibility belongs to field metadata (Depends On / Customize Form);
		// the currency only drives its required-ness and value.
		frm.toggle_reqd("receipt_payer_exchange_rate", Boolean(foreignPayer));
		frm.set_df_property(
			"receipt_payer_exchange_rate",
			"formatter",
			isReceipt ? compactNumberFormatter : null,
		);
		if (isReceipt) {
			configureCompactNumberInput(frm.fields_dict.receipt_payer_exchange_rate);
		}
		frm.toggle_display("company_currency", !isReceipt);
		// General Reference is not part of the normal Receipt workflow; other operation
		// types keep it (field and historical values untouched).
		frm.toggle_display("general_reference", !isReceipt);
	},
	applyReceiverKindLabels(frm) {
		const df = frm.fields_dict.receipt_receiver_kind?.df;
		if (!df || Array.isArray(df.options)) {
			return;
		}
		const values = String(df.options || "").split("\n").filter(Boolean);
		if (!values.length) {
			return;
		}
		frm.set_df_property(
			"receipt_receiver_kind",
			"options",
			values.map((value) => ({ value, label: RECEIVER_KIND_LABELS[value] || value })),
		);
	},
	configureGrid(frm, isReceipt) {
		const grid = frm.fields_dict.operational_pairs?.grid;
		if (!grid) {
			return;
		}
		const gridWrapper = frm.fields_dict.operational_pairs.$wrapper;
		gridWrapper.closest(".form-section").toggleClass("sp-receipt-layout-section", isReceipt);
		gridWrapper.toggleClass("sp-receipt-wide-grid", isReceipt);
		frm.fields_dict.receipt_summary?.$wrapper.toggleClass("sp-receipt-wide-grid", isReceipt);
		if (isReceipt && frm.doc.posting_date) {
			for (const row of frm.doc.operational_pairs || []) {
				if (!row.receipt_posting_date) {
					void frappe.model.set_value(
						row.doctype,
						row.name,
						"receipt_posting_date",
						frm.doc.posting_date,
					);
				}
			}
		}
		for (const fieldname of RECEIPT_FIELDS) {
			grid.toggle_display(fieldname, isReceipt);
		}
		for (const fieldname of TECHNICAL_RECEIPT_FIELDS) {
			grid.toggle_display(fieldname, !isReceipt);
		}
		grid.set_column_disp_in_list_view(RECEIPT_FIELDS, isReceipt);
		grid.set_column_disp_in_list_view("receipt_posting_date", false);
		grid.set_column_disp_in_list_view(TECHNICAL_RECEIPT_FIELDS, !isReceipt);
		grid.set_column_disp_in_list_view(["credit_account", "credit_amount"], true);
		grid.toggle_display("receipt_payer_exchange_rate", false);
		grid.set_column_disp_in_list_view("receipt_payer_exchange_rate", false);
		grid.toggle_display("credit_description", true);
		grid.toggle_display("credit_rate_direction", true);
		grid.set_column_disp_in_list_view(["credit_description", "credit_rate_direction"], false);
		if (!isReceipt) {
			grid.set_column_disp_in_list_view(["debit_exchange_rate", "debit_company_amount"], false);
			grid.toggle_display("debit_exchange_rate", true);
			grid.toggle_display("debit_company_amount", true);
			renderGridProperties(grid, [
				["receipt_recipient_type", "reqd", 0],
				["receipt_currency", "reqd", 0],
				["debit_account", "reqd", 0],
				["debit_amount", "reqd", 0],
				["credit_account", "reqd", 0],
				["credit_amount", "reqd", 0],
				["debit_account", "label", "Account"],
				["debit_exchange_rate", "label", "Exchange Rate"],
				["debit_company_amount", "label", "Company Currency Amount"],
				["debit_rate_direction", "label", "Rate Meaning"],
				["debit_description", "label", "Line Description"],
				["details_section", "label", "More Details"],
				["tracking_number", "label", "Tracking Number"],
				["transfer_reference", "label", "Transfer Reference"],
				["cheque_number", "label", "Cheque Number"],
				["cheque_date", "label", "Cheque Date"],
				["bank_reference", "label", "Bank Reference"],
				["deposit_identifier", "label", "Deposit Identifier"],
				["depositor_name", "label", "Depositor Name"],
				["bank_name", "label", "Bank Name"],
				["debit_account", "columns", 3],
				["debit_amount", "columns", 2],
				["debit_amount", "label", "Amount"],
				["credit_account", "label", "Account"],
				["credit_exchange_rate", "label", "Exchange Rate"],
				["credit_company_amount", "label", "Company Currency Amount"],
				["credit_rate_direction", "label", "Rate Meaning"],
				["credit_description", "label", "Line Description"],
				["credit_amount", "label", "Amount"],
				...RECEIPT_NUMBER_FIELDS.map((fieldname) => [fieldname, "formatter", null]),
			]);
			this.renderSummary(frm);
			return;
		}

		const rows = frm.doc.operational_pairs || [];
		const currencies = new Set(rows.map((row) => row.receipt_currency).filter(Boolean));
		const hasForeign = rows.some(
			(row) => row.receipt_currency && row.receipt_currency !== frm.doc.company_currency,
		);
		const hasPartyRecipient = rows.some(
			(row) => row.receipt_recipient_type !== ACCOUNT_RECIPIENT,
		);
		grid.toggle_display(
			"receipt_recipient",
			hasPartyRecipient,
		);
		grid.toggle_display("credit_exchange_rate", hasForeign);
		grid.toggle_display("credit_company_amount", hasForeign);
		grid.set_column_disp_in_list_view("receipt_recipient", hasPartyRecipient);
		grid.set_column_disp_in_list_view("credit_exchange_rate", hasForeign);
		grid.set_column_disp_in_list_view("credit_company_amount", hasForeign);
		const visibleColumns = receiptGridColumns(hasPartyRecipient, hasForeign);
		renderGridProperties(grid, [
			["receipt_recipient_type", "reqd", 1],
			["receipt_currency", "reqd", 1],
			["credit_account", "reqd", 1],
			["credit_amount", "reqd", 1],
			["receipt_recipient_type", "label", "نوع پرداخت‌کننده"],
			["receipt_recipient", "label", "نام پرداخت‌کننده"],
			["credit_account", "label", "معین پرداخت‌کننده"],
			["credit_exchange_rate", "label", "نرخ"],
			["credit_company_amount", "label", "مبلغ به ارز پایه"],
			["credit_rate_direction", "label", "معنی نرخ"],
			["credit_description", "label", "توضیح"],
			["details_section", "label", "جزئیات بیشتر"],
			["tracking_number", "label", "شماره پیگیری"],
			["transfer_reference", "label", "مرجع انتقال"],
			["cheque_number", "label", "شماره چک"],
			["cheque_date", "label", "تاریخ چک"],
			["bank_reference", "label", "مرجع بانکی"],
			["deposit_identifier", "label", "شناسه واریز"],
			["depositor_name", "label", "نام واریزکننده"],
			["bank_name", "label", "نام بانک / بانک مبدأ"],
			["receipt_posting_date", "columns", 1],
			["receipt_currency", "columns", 1],
			["receipt_recipient_type", "columns", 2],
			["receipt_recipient", "columns", 5],
			["credit_account", "columns", 4],
			["credit_amount", "columns", 2],
			["credit_exchange_rate", "columns", 2],
			["credit_company_amount", "columns", 3],
			...RECEIPT_NUMBER_FIELDS.map((fieldname) => [fieldname, "formatter", compactNumberFormatter]),
			[
				"credit_amount",
				"label",
				currencies.size > 1 ? __("مبلغ / مبلغ ارز") : hasForeign ? __("مبلغ ارز") : __("مبلغ"),
			],
		], visibleColumns);
		for (const row of rows) {
			if (row.__sp_previous_receipt_currency === undefined) {
				row.__sp_previous_receipt_currency = row.receipt_currency || "";
			}
			this.configureGridRow(frm, row);
		}
		this.renderSummary(frm);
	},
	refreshReceiptView(frm) {
		if (frm.doc.operation_type !== RECEIPT) {
			this.renderSummary(frm);
			return;
		}
		this.configureHeader(frm, true);
		this.configureGrid(frm, true);
		this.renderSummary(frm);
	},
	renderSummary(frm) {
		const field = frm.fields_dict.receipt_summary;
		if (!field || frm.doc.operation_type !== RECEIPT) {
			field?.$wrapper.empty();
			return;
		}
		const summarize = window.smartprocessAccounting?.numeric?.summarizeReceiptRows;
		if (!summarize) {
			field.$wrapper.empty();
			return;
		}
		const summary = summarize(frm.doc.operational_pairs || [], frm.doc.company_currency);
		const rows = summary.currencies.map((row) => {
			const rate = row.weightedRate === null ? "—" : formatReceiptSummaryValue(row.weightedRate);
			return `<tr>
				<td>${frappe.utils.escape_html(row.currency)}</td>
				<td>${formatReceiptSummaryValue(row.amount)}</td>
				<td>${rate}</td>
				<td>${formatReceiptSummaryValue(row.baseAmount)}</td>
			</tr>`;
		}).join("");
		field.$wrapper.html(`<div class="sp-receipt-summary">
			<table class="table table-bordered">
				<thead><tr><th>ارز</th><th>مجموع دریافت همان ارز</th><th>میانگین وزنی نرخ</th><th>مجموع به ارز پایه</th></tr></thead>
				<tbody>${rows || '<tr><td colspan="4" class="text-muted">ردیف معتبری برای خلاصه وجود ندارد.</td></tr>'}</tbody>
			</table>
			<div class="sp-receipt-summary-total"><strong>جمع کل به ارز پایه:</strong> ${formatReceiptSummaryValue(summary.companyTotal)}</div>
			${receiverTotalMarkup()}
		</div>`);
		this.scheduleReceiverTotalRefresh(frm);
	},
	scheduleReceiverTotalRefresh(frm) {
		clearTimeout(frm.__sp_receiver_total_timeout);
		frm.__sp_receiver_total_timeout = setTimeout(() => {
			void this.refreshReceiverTotal(frm);
		}, 300);
	},
	async refreshReceiverTotal(frm) {
		const target = frm.fields_dict.receipt_summary?.$wrapper
			.find(".sp-receipt-receiver-values").get(0);
		if (!target || frm.doc.operation_type !== RECEIPT) {
			return;
		}
		if (!canCalculateLiveReceiptSummary(frm)) {
			this.showReceiverTotalNotReady(target);
			return;
		}
		const requestNumber = (frm.__sp_receiver_total_request || 0) + 1;
		frm.__sp_receiver_total_request = requestNumber;
		try {
			const { message } = await frappe.call({
				method: "smartprocess_erpnext_accounting.smartprocess_accounting.v2_api.get_receipt_receiver_total",
				args: { doc: receiptReceiverTotalPayload(frm) },
			});
			if (frm.__sp_receiver_total_request !== requestNumber) {
				return;
			}
			const currentTarget = frm.fields_dict.receipt_summary?.$wrapper
				.find(".sp-receipt-receiver-values").get(0);
			if (!currentTarget) {
				return;
			}
			if (!message) {
				this.showReceiverTotalNotReady(currentTarget);
				return;
			}
			currentTarget.classList.remove("text-muted");
			currentTarget.innerHTML = receiverTotalLine(message);
		} catch (error) {
			if (frm.__sp_receiver_total_request !== requestNumber) {
				return;
			}
			const currentTarget = frm.fields_dict.receipt_summary?.$wrapper
				.find(".sp-receipt-receiver-values").get(0);
			if (currentTarget) {
				this.showReceiverTotalNotReady(currentTarget);
			}
			if (error?.exc_type && error.exc_type !== "ValidationError") {
				console.error("receiver-total display error:", error);
			}
		}
	},
	showReceiverTotalNotReady(target) {
		target.classList.add("text-muted");
		target.innerHTML = "—";
	},
	configureGridRow(frm, row) {
		const grid = frm.fields_dict.operational_pairs?.grid;
		const activeGridRow = frm.cur_grid?.doc?.name === row.name ? frm.cur_grid : null;
		const gridRow = activeGridRow || grid?.grid_rows_by_docname?.[row.name];
		if (!gridRow) {
			return;
		}
		const foreign = row.receipt_currency && row.receipt_currency !== frm.doc.company_currency;
		const hasForeign = (frm.doc.operational_pairs || []).some(
			(candidate) => candidate.receipt_currency
				&& candidate.receipt_currency !== frm.doc.company_currency,
		);
		for (const [fieldname, label] of [
			["receipt_recipient_type", "نوع پرداخت‌کننده"],
			["receipt_recipient", "نام پرداخت‌کننده"],
			["credit_column", "پرداخت"],
			["credit_account", "معین پرداخت‌کننده"],
			["credit_amount", foreign ? "مبلغ ارز" : "مبلغ"],
			["credit_exchange_rate", "نرخ"],
			["credit_company_amount", "مبلغ به ارز پایه"],
			["credit_rate_direction", "معنی نرخ"],
			["credit_description", "توضیح"],
			["details_section", "جزئیات بیشتر"],
			["tracking_number", "شماره پیگیری"],
			["transfer_reference", "مرجع انتقال"],
			["cheque_number", "شماره چک"],
			["cheque_date", "تاریخ چک"],
			["bank_reference", "مرجع بانکی"],
			["deposit_identifier", "شناسه واریز"],
			["depositor_name", "نام واریزکننده"],
			["bank_name", "نام بانک / بانک مبدأ"],
		]) {
			gridRow.set_field_property(fieldname, "label", label);
		}
		gridRow.set_field_property(
			"receipt_recipient",
			"label",
			row.receipt_recipient_type === BANK_ACCOUNT_RECIPIENT ? "حساب بانکی" : "نام پرداخت‌کننده",
		);
		gridRow.toggle_display("receipt_recipient", row.receipt_recipient_type !== ACCOUNT_RECIPIENT);
		gridRow.toggle_display("credit_exchange_rate", hasForeign);
		gridRow.toggle_display("credit_company_amount", hasForeign);
		gridRow.toggle_editable("credit_exchange_rate", Boolean(foreign));
		gridRow.toggle_display("credit_rate_direction", Boolean(foreign));
		gridRow.toggle_display("credit_description", true);
		gridRow.toggle_display("receipt_payer_exchange_rate", false);
		configureReceiptGridRowLifecycle(gridRow);
	},
	async loadCurrencyOptions(frm, force = false) {
		if (frm.doc.operation_type !== RECEIPT || !frm.doc.company) {
			this.applyCurrencyOptions(frm, []);
			return;
		}
		if (!force && frm.__sp_currency_options_company === frm.doc.company) {
			this.applyCurrencyOptions(frm, frm.__sp_currency_options || []);
			return;
		}

		const requestedCompany = frm.doc.company;
		const requestNumber = (frm.__sp_currency_options_request || 0) + 1;
		frm.__sp_currency_options_request = requestNumber;
		const { message } = await frappe.call({
			type: "GET",
			method: "smartprocess_erpnext_accounting.smartprocess_accounting.v2_api.get_receipt_currency_options",
			args: { company: requestedCompany },
		});
		if (frm.doc.company !== requestedCompany || frm.__sp_currency_options_request !== requestNumber) {
			return;
		}
		frm.__sp_currency_options_company = requestedCompany;
		frm.__sp_currency_options = message || [];
		this.applyCurrencyOptions(frm, frm.__sp_currency_options);
	},
	applyCurrencyOptions(frm, availableCurrencies) {
		const storedCurrencies = [
			frm.doc.receipt_payer_currency,
			...(frm.doc.operational_pairs || []).map((row) => row.receipt_currency),
		].filter(Boolean);
		// No leading "" — a blank option must never be selectable; the default value comes
		// from Company.default_currency (header) or the Party/account state logic (rows).
		const options = [...new Set([...availableCurrencies, ...storedCurrencies])].filter(Boolean);
		const optionText = options.join("\n");
		frm.set_df_property("receipt_payer_currency", "options", optionText);

		const grid = frm.fields_dict.operational_pairs?.grid;
		if (!grid) {
			return;
		}
		for (const field of [
			frappe.meta.docfield_map["SmartProcess Accounting Pair"]?.receipt_currency,
			frappe.meta.get_docfield("SmartProcess Accounting Pair", "receipt_currency", frm.docname),
		]) {
			if (field) {
				field.options = optionText;
			}
		}
		grid.__sp_receipt_currency_options = optionText;
		updateGridProperty(grid, "receipt_currency", "options", optionText);
		grid.refresh();
		for (const gridRow of grid.grid_rows || []) {
			const rowField = gridRow.docfields?.find(
				(field) => field.fieldname === "receipt_currency",
			);
			if (rowField) {
				rowField.options = optionText;
			}
			gridRow.set_field_property("receipt_currency", "options", optionText);
		}
	},
	async headerPartyChanged(frm) {
		if (frm.doc.operation_type !== RECEIPT) {
			return;
		}
		if (frm.doc.receipt_payer_account) {
			await frm.set_value("receipt_payer_account", "");
		}
		// Currency is chosen first and is authoritative: the Party must match it.
		// Server-side compatibility (ledger currency, then native account currency)
		// confirms the choice; an incompatible Party is rejected and cleared.
		const context = await getHeaderPartyContext(frm);
		if (context) {
			const partyCurrency = context.ledger_currency || context.account_currency || "";
			if (frm.doc.receipt_payer_currency) {
				if (partyCurrency && partyCurrency !== frm.doc.receipt_payer_currency) {
					const rejectedParty = frm.doc.receipt_payer;
					await frm.set_value("receipt_payer", "");
					frappe.msgprint(
						partyCurrencyMismatchMessage(
							rejectedParty,
							partyCurrency,
							frm.doc.receipt_payer_currency,
						),
					);
					await this.refreshReceiptView(frm);
					return;
				}
			} else if (partyCurrency) {
				// Convenience fill only when no currency has been chosen yet.
				frm.__sp_receiver_currency_explicit = false;
				await this.setProgrammaticReceiverCurrency(frm, partyCurrency);
			}
		}
		await this.suggestPayerAccount(frm);
		await this.refreshReceiptView(frm);
	},
	async syncReceiverCurrencyFromParty(frm) {
		// Draft-load convenience: fill an empty currency from the Party, never
		// override a currency the user already chose.
		if (
			frm.doc.operation_type !== RECEIPT
			|| !frm.doc.company
			|| !frm.doc.receipt_payer_type
			|| !frm.doc.receipt_payer
			|| !PARTY_TYPES.includes(frm.doc.receipt_payer_type)
			|| frm.doc.receipt_payer_currency
		) {
			return;
		}
		const context = await getPartyCurrencyContextSafely(
			frm.doc.receipt_payer_type,
			frm.doc.receipt_payer,
			frm.doc.company,
		);
		const currency = context.ledger_currency || context.account_currency || "";
		if (currency) {
			frm.__sp_receiver_currency_explicit = false;
			await this.setProgrammaticReceiverCurrency(frm, currency);
		}
	},
	async setProgrammaticReceiverCurrency(frm, currency) {
		if (!currency || frm.doc.receipt_payer_currency === currency) {
			return;
		}
		frm.__sp_setting_receiver_currency = true;
		try {
			await frm.set_value("receipt_payer_currency", currency);
		} finally {
			frm.__sp_setting_receiver_currency = false;
		}
	},
	async headerTypeChanged(frm) {
		if (frm.doc.operation_type !== RECEIPT) {
			return;
		}
		frm.__sp_receiver_currency_explicit = false;
		const receiverKind = frm.doc.receipt_receiver_kind;
		const partyType = PARTY_TYPES.includes(receiverKind) ? receiverKind : "";
		await frm.set_value("receipt_payer_type", partyType);
		await frm.set_value("receipt_payer_account", "");
		await frm.set_value("receipt_bank_account", "");
		await frm.set_value("receipt_payer", "");
		await this.defaultReceiverCurrency(frm, frm.doc.company_currency || "");
		await this.refreshReceiptView(frm);
	},
	async headerCurrencyChanged(frm) {
		if (frm.doc.operation_type !== RECEIPT) {
			return;
		}
		if (frm.__sp_setting_receiver_currency) {
			return this.applyReceiverCurrency(frm);
		}
		if (frm.doc.receipt_payer_currency) {
			frm.__sp_receiver_currency_explicit = true;
		}
		// Currency is the first choice: dependents that do not match the new
		// currency are cleared at once, and the queries rebuild from live state.
		await this.clearIncompatibleHeaderReceiver(frm);
		return this.applyReceiverCurrency(frm);
	},
	async clearIncompatibleHeaderReceiver(frm) {
		const currency = frm.doc.receipt_payer_currency;
		if (!currency || !frm.doc.company) {
			return;
		}
		if (frm.doc.receipt_receiver_kind === "بانک" && frm.doc.receipt_bank_account) {
			const details = await getBankAccountDetailsSafely(
				frm.doc.receipt_bank_account,
				frm.doc.company,
			);
			if (details?.account_currency && details.account_currency !== currency) {
				await frm.set_value("receipt_bank_account", "");
				await frm.set_value("receipt_payer_account", "");
			}
			return;
		}
		if (PARTY_TYPES.includes(frm.doc.receipt_payer_type) && frm.doc.receipt_payer) {
			const context = await getPartyCurrencyContextSafely(
				frm.doc.receipt_payer_type,
				frm.doc.receipt_payer,
				frm.doc.company,
			);
			const partyCurrency = context.ledger_currency || context.account_currency || "";
			if (partyCurrency && partyCurrency !== currency) {
				await frm.set_value("receipt_payer", "");
				await frm.set_value("receipt_payer_account", "");
			}
		}
	},
	async applyReceiverCurrency(frm) {
		if (frm.doc.operation_type !== RECEIPT) {
			return;
		}
		const previousCurrency = frm.__sp_previous_payer_currency || "";
		const currentCurrency = frm.doc.receipt_payer_currency || "";
		frm.__sp_previous_payer_currency = currentCurrency;
		await this.ensurePayerAccountCurrency(frm, false);
		if (currentCurrency && currentCurrency === frm.doc.company_currency) {
			await frm.set_value("receipt_payer_exchange_rate", 1);
		} else if (currentCurrency !== previousCurrency) {
			// Fresh foreign currency: 0 is only the UI default, never a valid
			// accounting rate — the user must enter the real one.
			await frm.set_value("receipt_payer_exchange_rate", 0);
		}
		await this.suggestPayerAccount(frm);
		await this.recalculatePayerRows(frm);
		await this.refreshReceiptView(frm);
	},
	async payerRateChanged(frm) {
		if (frm.doc.operation_type !== RECEIPT) {
			return;
		}
		if (frm.doc.receipt_payer_currency === frm.doc.company_currency) {
			if (Number(frm.doc.receipt_payer_exchange_rate) !== 1) {
				await frm.set_value("receipt_payer_exchange_rate", 1);
			}
		} else if (Number(frm.doc.receipt_payer_exchange_rate) > 0 && frm.doc.receipt_payer_account) {
			// The user progressed beyond Rate with an Account already picked: now is the
			// right stage to check the Account against the Receiver Currency.
			await this.ensurePayerAccountCurrency(frm, true);
		}
		await this.recalculatePayerRows(frm);
		this.renderSummary(frm);
	},
	// Staged header readiness, in interaction order: ارز → نوع دریافت‌کننده →
	// دریافت‌کننده → نرخ (foreign only) → معین. Returns null when the header is
	// complete enough.
	headerReadinessIssue(frm) {
		if (frm.doc.operation_type !== RECEIPT) {
			return null;
		}
		if (!frm.doc.receipt_payer_currency) {
			return ["receipt_payer_currency", __("ابتدا ارز دریافت‌کننده را تعیین کنید.")];
		}
		if (!frm.doc.receipt_receiver_kind) {
			return ["receipt_receiver_kind", __("ابتدا نوع دریافت‌کننده را انتخاب کنید.")];
		}
		if (PARTY_TYPES.includes(frm.doc.receipt_receiver_kind) && !frm.doc.receipt_payer) {
			return ["receipt_payer", __("ابتدا دریافت‌کننده را انتخاب کنید.")];
		}
		if (frm.doc.receipt_receiver_kind === "بانک" && !frm.doc.receipt_bank_account) {
			return ["receipt_bank_account", __("ابتدا حساب بانکی دریافت‌کننده را انتخاب کنید.")];
		}
		if (
			frm.doc.receipt_payer_currency !== frm.doc.company_currency
			&& !(Number(frm.doc.receipt_payer_exchange_rate) > 0)
		) {
			return ["receipt_payer_exchange_rate", __("برای دریافت‌کننده ارزی، نرخ ارز دریافت‌کننده الزامی و باید بزرگ‌تر از صفر باشد.")];
		}
		if (!frm.doc.receipt_payer_account) {
			return ["receipt_payer_account", __("ابتدا معین دریافت‌کننده را انتخاب کنید.")];
		}
		return null;
	},
	isHeaderReadyForRows(frm) {
		return frm.doc.operation_type === RECEIPT && !this.headerReadinessIssue(frm);
	},
	// First meaningful child-row entry requires a complete-enough header: one clear
	// error and focus on the missing field instead of cascading popups.
	ensureHeaderReadyForRows(frm) {
		const issue = this.headerReadinessIssue(frm);
		if (!issue) {
			return true;
		}
		frappe.msgprint({
			title: __("تکمیل سربرگ دریافت"),
			message: issue[1],
			indicator: "orange",
		});
		frm.scroll_to_field(issue[0]);
		return false;
	},
	async recalculatePayerRows(frm) {
		for (const row of frm.doc.operational_pairs || []) {
			await spAccountingPair.calculateReceiptReceiver(frm, row.doctype, row.name);
		}
	},
	async parentPostingDateChanged(frm) {
		if (frm.doc.operation_type !== RECEIPT || !frm.doc.posting_date) {
			return;
		}
		for (const row of frm.doc.operational_pairs || []) {
			if (!row.receipt_posting_date) {
				await frappe.model.set_value(
					row.doctype,
					row.name,
					"receipt_posting_date",
					frm.doc.posting_date,
				);
			}
		}
	},
	async headerAccountChanged(frm) {
		const userInitiated = !frm.__sp_setting_payer_account;
		if (userInitiated) {
			const foreign = frm.doc.receipt_payer_currency
				&& frm.doc.receipt_payer_currency !== frm.doc.company_currency;
			if (
				foreign
				&& frm.doc.receipt_payer_account
				&& !(Number(frm.doc.receipt_payer_exchange_rate) > 0)
			) {
				frappe.msgprint({
					title: __("نرخ ارز دریافت‌کننده"),
					message: __("برای دریافت‌کننده ارزی، نرخ ارز دریافت‌کننده الزامی و باید بزرگ‌تر از صفر باشد."),
					indicator: "orange",
				});
				frm.scroll_to_field("receipt_payer_exchange_rate");
				return;
			}
		}
		await this.ensurePayerAccountCurrency(frm, userInitiated);
		await this.refreshReceiptView(frm);
	},
	async ensurePayerAccountCurrency(frm, notify) {
		if (frm.doc.operation_type !== RECEIPT || !frm.doc.receipt_payer_account || !frm.doc.company) {
			return;
		}
		const details = await getAccountDetails(frm.doc.receipt_payer_account, frm.doc.company);
		if (details.account_currency !== frm.doc.receipt_payer_currency) {
			await frm.set_value("receipt_payer_account", "");
			if (notify) {
				frappe.msgprint(__("ارز معین دریافت‌کننده با ارز دریافت‌کننده یکسان نیست."));
			}
		}
	},
	async headerBankChanged(frm) {
		if (frm.doc.operation_type !== RECEIPT || frm.doc.receipt_receiver_kind !== "بانک") {
			return;
		}
		if (!frm.doc.receipt_bank_account || !frm.doc.company) {
			await frm.set_value("receipt_payer_account", "");
			await this.refreshReceiptView(frm);
			return;
		}
		const details = await getBankAccountDetails(frm.doc.receipt_bank_account, frm.doc.company);
		// The Bank Account list is filtered by the selected currency, so a mismatch
		// here is stale state: reject the Bank Account instead of changing currency.
		if (
			frm.doc.receipt_payer_currency
			&& details.account_currency
			&& frm.doc.receipt_payer_currency !== details.account_currency
		) {
			await frm.set_value("receipt_bank_account", "");
			await frm.set_value("receipt_payer_account", "");
			frappe.msgprint(__("حساب بانکی انتخاب‌شده با ارز دریافت‌کننده یکسان نیست."));
			await this.refreshReceiptView(frm);
			return;
		}
		if (!frm.doc.receipt_payer_currency) {
			await this.setProgrammaticReceiverCurrency(frm, details.account_currency);
		}
		frm.__sp_setting_payer_account = true;
		try {
			await frm.set_value("receipt_payer_account", details.account);
		} finally {
			frm.__sp_setting_payer_account = false;
		}
		await this.refreshReceiptView(frm);
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
		const account = await getReceiptSuggestionSafely(
			frm.doc.receipt_payer_type,
			frm.doc.receipt_payer,
			frm.doc.company,
			frm.doc.receipt_payer_currency,
		);
		if (account && !frm.doc.receipt_payer_account) {
			frm.__sp_setting_payer_account = true;
			try {
				await frm.set_value("receipt_payer_account", account);
			} finally {
				frm.__sp_setting_payer_account = false;
			}
		}
	},
};

function canStartCorrection(frm) {
	const hasPermission = (permissionType) =>
		(frm.perm || []).some((permission) => Boolean(permission[permissionType]));
	return [1, 2].includes(frm.doc.docstatus)
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

async function getPartyCurrencyContext(partyType, party, company) {
	const { message } = await frappe.call({
		type: "GET",
		method: "smartprocess_erpnext_accounting.smartprocess_accounting.v2_api.get_party_currency_context",
		args: { party_type: partyType, party, company },
	});
	return message || {};
}

// Mid-edit lookups may hit a half-updated document (new type, old party, …). Those
// validation failures are expected during a state transition and must not surface as
// popups; anything else is a real programming error and is re-thrown.
async function getPartyCurrencyContextSafely(partyType, party, company) {
	try {
		return await getPartyCurrencyContext(partyType, party, company);
	} catch (error) {
		if (error?.exc_type === "ValidationError") {
			return {};
		}
		throw error;
	}
}

async function getAccountDetailsSafely(account, company) {
	try {
		return await getAccountDetails(account, company);
	} catch (error) {
		if (error?.exc_type === "ValidationError") {
			return null;
		}
		throw error;
	}
}

async function getReceiptSuggestionSafely(partyType, party, company, currency) {
	try {
		return await getReceiptSuggestion(partyType, party, company, currency);
	} catch (error) {
		if (error?.exc_type === "ValidationError") {
			return "";
		}
		throw error;
	}
}

async function getBankAccountDetails(bankAccount, company) {
	const { message } = await frappe.call({
		method: "smartprocess_erpnext_accounting.smartprocess_accounting.v2_api.get_bank_account_details",
		args: { bank_account: bankAccount, company },
	});
	return message || {};
}

async function getBankAccountDetailsSafely(bankAccount, company) {
	try {
		return await getBankAccountDetails(bankAccount, company);
	} catch (error) {
		if (error?.exc_type === "ValidationError") {
			return null;
		}
		throw error;
	}
}

async function getHeaderPartyContext(frm) {
	if (!PARTY_TYPES.includes(frm.doc.receipt_payer_type) || !frm.doc.receipt_payer) {
		return null;
	}
	return getPartyCurrencyContextSafely(
		frm.doc.receipt_payer_type,
		frm.doc.receipt_payer,
		frm.doc.company,
	);
}

function partyCurrencyMismatchMessage(party, partyCurrency, targetCurrency) {
	return __(
		"«{0}» با ارز {1} ثبت یا تعریف شده است و با ارز {2} همخوان نیست؛ دریافت‌کنندهٔ دیگری انتخاب کنید.",
		[party, partyCurrency, targetCurrency],
	);
}

const spAccountingPair = {
	async refresh_account(frm, cdt, cdn, side) {
		const row = locals[cdt][cdn];
		const account = row[`${side}_account`];
		if (!account || !frm.doc.company) {
			return;
		}
		if (frm.doc.operation_type === RECEIPT && side === "credit") {
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
		if (!row.credit_account) {
			return;
		}
		const details = await getAccountDetails(row.credit_account, frm.doc.company);
		if (details.account_currency !== row.receipt_currency) {
			await frappe.model.set_value(cdt, cdn, "credit_account", "");
			frappe.msgprint(__("ارز معین پرداخت‌کننده با ارز ردیف یکسان نیست."));
			return;
		}
		await frappe.model.set_value(cdt, cdn, "credit_account_currency", details.account_currency);
		await frappe.model.set_value(cdt, cdn, "company_currency", frm.doc.company_currency);
		await this.calculate(frm, cdt, cdn, "credit");
	},
	async calculate(frm, cdt, cdn, side) {
		const row = locals[cdt][cdn];
		if (row.__sp_calculating) {
			return;
		}
		row.__sp_calculating = true;
		try {
			const accountCurrency = frm.doc.operation_type === RECEIPT && side === "credit"
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
			if (frm.doc.operation_type === RECEIPT && side === "credit") {
				await this.calculateReceiptReceiver(frm, cdt, cdn);
				receiptForm.renderSummary(frm);
			}
		} finally {
			row.__sp_calculating = false;
		}
	},
	async calculateReceiptReceiver(frm, cdt, cdn) {
		if (frm.doc.operation_type !== RECEIPT) {
			return;
		}
		const row = locals[cdt][cdn];
		const companyAmount = Number(row.credit_company_amount || 0);
		const receiverCurrency = frm.doc.receipt_payer_currency;
		const baseReceiver = receiverCurrency && receiverCurrency === frm.doc.company_currency;
		const receiverRate = baseReceiver ? 1 : Number(frm.doc.receipt_payer_exchange_rate || 0);
		const receiverAmount = companyAmount > 0 && receiverRate > 0
			? companyAmount / receiverRate
			: 0;
		await frappe.model.set_value(cdt, cdn, "debit_account_currency", receiverCurrency || "");
		await frappe.model.set_value(cdt, cdn, "debit_exchange_rate", receiverRate || "");
		await frappe.model.set_value(cdt, cdn, "debit_amount", receiverAmount || "");
		await frappe.model.set_value(cdt, cdn, "debit_company_amount", companyAmount || "");
		const meaning = receiverCurrency && frm.doc.company_currency && receiverRate > 0
			? `1 ${receiverCurrency} = ${receiverRate} ${frm.doc.company_currency}`
			: "";
		await frappe.model.set_value(cdt, cdn, "debit_rate_direction", meaning);
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
	async rowTypeChanged(frm, cdt, cdn) {
		if (frm.doc.operation_type !== RECEIPT) {
			return;
		}
		const row = locals[cdt][cdn];
		if (row.__sp_receipt_copying) {
			return;
		}
		// The user is starting to enter this row: the header must be staged-complete.
		receiptForm.ensureHeaderReadyForRows(frm);
		// Clearing receipt_recipient is a side effect of this one user action, not a
		// second row entry: keep rowPartyChanged from re-running the header check.
		row.__sp_row_party_guard = true;
		try {
			await frappe.model.set_value(cdt, cdn, "receipt_recipient", "");
		} finally {
			row.__sp_row_party_guard = false;
		}
		await frappe.model.set_value(cdt, cdn, "credit_account", "");
		// Currency comes first in the row: default it only when the user has not
		// chosen one; an existing choice (possibly foreign) is kept on Type change.
		if (!row.receipt_currency) {
			await this.setRowReceiptCurrency(frm, cdt, cdn, frm.doc.company_currency || "");
		}
		receiptForm.configureGrid(frm, true);
		receiptForm.renderSummary(frm);
	},
	async rowPartyChanged(frm, cdt, cdn) {
		if (frm.doc.operation_type !== RECEIPT) {
			return;
		}
		const row = locals[cdt][cdn];
		if (row.__sp_receipt_copying || row.__sp_row_party_guard) {
			return;
		}
		receiptForm.ensureHeaderReadyForRows(frm);
		await frappe.model.set_value(cdt, cdn, "credit_account", "");
		if (row.receipt_recipient_type === BANK_ACCOUNT_RECIPIENT) {
			await this.applyRowBankAccount(frm, cdt, cdn);
		} else {
			await this.verifyRowEntityMatchesCurrency(frm, cdt, cdn);
			await this.suggestReceiptAccount(frm, cdt, cdn);
		}
		receiptForm.configureGrid(frm, true);
		receiptForm.renderSummary(frm);
	},
	async applyRowBankAccount(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.receipt_recipient || !frm.doc.company) {
			return;
		}
		const details = await getBankAccountDetails(row.receipt_recipient, frm.doc.company);
		// The Bank Account list is filtered by the row currency, so a mismatch here
		// is stale state: reject the Bank Account instead of changing the currency.
		if (row.receipt_currency && details.account_currency && row.receipt_currency !== details.account_currency) {
			await this.rejectRowEntity(
				frm,
				cdt,
				cdn,
				__("حساب بانکی انتخاب‌شده با ارز ردیف یکسان نیست."),
			);
			return;
		}
		if (!row.receipt_currency && details.account_currency) {
			await this.setRowReceiptCurrency(frm, cdt, cdn, details.account_currency);
		}
		await frappe.model.set_value(cdt, cdn, "credit_account", details.account);
		await this.calculate(frm, cdt, cdn, "credit");
	},
	// The row Entity (Party or Account) must match the row currency chosen first.
	// Server-side compatibility (ledger currency, then native account currency)
	// confirms the choice; an incompatible Entity is rejected and cleared, and an
	// empty row currency is filled from the Entity as a convenience only.
	async verifyRowEntityMatchesCurrency(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!frm.doc.company || !row.receipt_recipient_type || !row.receipt_recipient) {
			return;
		}
		if (row.receipt_recipient_type === ACCOUNT_RECIPIENT) {
			const details = await getAccountDetailsSafely(row.receipt_recipient, frm.doc.company);
			const accountCurrency = details?.account_currency || "";
			if (!accountCurrency) {
				return;
			}
			if (row.receipt_currency) {
				if (row.receipt_currency !== accountCurrency) {
					await this.rejectRowEntity(
						frm,
						cdt,
						cdn,
						__("حساب انتخاب‌شده با ارز ردیف یکسان نیست."),
					);
				}
				return;
			}
			await this.setRowReceiptCurrency(frm, cdt, cdn, accountCurrency);
			return;
		}
		if (!PARTY_TYPES.includes(row.receipt_recipient_type)) {
			return;
		}
		const context = await getPartyCurrencyContextSafely(
			row.receipt_recipient_type,
			row.receipt_recipient,
			frm.doc.company,
		);
		const currency = context.ledger_currency || context.account_currency || "";
		if (!currency) {
			return;
		}
		if (row.receipt_currency) {
			if (row.receipt_currency !== currency) {
				await this.rejectRowEntity(
					frm,
					cdt,
					cdn,
					partyCurrencyMismatchMessage(row.receipt_recipient, currency, row.receipt_currency),
				);
			}
			return;
		}
		await this.setRowReceiptCurrency(frm, cdt, cdn, currency);
	},
	async rejectRowEntity(frm, cdt, cdn, message) {
		const row = locals[cdt][cdn];
		row.__sp_row_party_guard = true;
		try {
			await frappe.model.set_value(cdt, cdn, "receipt_recipient", "");
		} finally {
			row.__sp_row_party_guard = false;
		}
		await frappe.model.set_value(cdt, cdn, "credit_account", "");
		frappe.msgprint(message);
	},
	async setRowReceiptCurrency(frm, cdt, cdn, currency) {
		const row = locals[cdt][cdn];
		if (!currency || row.receipt_currency === currency) {
			return;
		}
		row.__sp_receipt_currency_guard = true;
		try {
			await frappe.model.set_value(cdt, cdn, "receipt_currency", currency);
		} finally {
			row.__sp_receipt_currency_guard = false;
		}
	},
	async rowCurrencyChanged(frm, cdt, cdn) {
		if (frm.doc.operation_type !== RECEIPT) {
			return;
		}
		const row = locals[cdt][cdn];
		if (!row.__sp_receipt_currency_guard) {
			// Only a user-initiated row Currency choice starts (or continues) row entry.
			receiptForm.ensureHeaderReadyForRows(frm);
			// Currency is the first row choice: an Entity that does not match the new
			// currency is cleared at once instead of reverting the currency.
			await this.clearIncompatibleRowEntity(frm, cdt, cdn);
		}
		return this.applyRowCurrency(frm, cdt, cdn);
	},
	async clearIncompatibleRowEntity(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.receipt_currency || !row.receipt_recipient || !row.receipt_recipient_type) {
			return;
		}
		const entityCurrency = await this.rowEntityCurrencySafely(frm, cdt, cdn);
		if (entityCurrency && entityCurrency !== row.receipt_currency) {
			row.__sp_row_party_guard = true;
			try {
				await frappe.model.set_value(cdt, cdn, "receipt_recipient", "");
			} finally {
				row.__sp_row_party_guard = false;
			}
			await frappe.model.set_value(cdt, cdn, "credit_account", "");
		}
	},
	async rowEntityCurrencySafely(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		try {
			if (row.receipt_recipient_type === ACCOUNT_RECIPIENT) {
				const details = await getAccountDetailsSafely(row.receipt_recipient, frm.doc.company);
				return details?.account_currency || "";
			}
			if (row.receipt_recipient_type === BANK_ACCOUNT_RECIPIENT) {
				const details = await getBankAccountDetails(row.receipt_recipient, frm.doc.company);
				return details.account_currency || "";
			}
			if (PARTY_TYPES.includes(row.receipt_recipient_type)) {
				const context = await getPartyCurrencyContextSafely(
					row.receipt_recipient_type,
					row.receipt_recipient,
					frm.doc.company,
				);
				return context.ledger_currency || context.account_currency || "";
			}
		} catch (error) {
			if (error?.exc_type === "ValidationError") {
				return "";
			}
			throw error;
		}
		return "";
	},
	async applyRowCurrency(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const changed = row.__sp_previous_receipt_currency !== undefined
			&& row.__sp_previous_receipt_currency !== row.receipt_currency;
		row.__sp_previous_receipt_currency = row.receipt_currency || "";
		receiptForm.configureGrid(frm, true);
		try {
			await frappe.model.set_value(cdt, cdn, "credit_account_currency", row.receipt_currency || "");
			if (changed && !row.__sp_receipt_copying) {
				await frappe.model.set_value(cdt, cdn, "credit_exchange_rate", "");
			}
			if (row.receipt_currency === frm.doc.company_currency) {
				await frappe.model.set_value(cdt, cdn, "credit_exchange_rate", 1);
			} else if (
				!row.credit_exchange_rate
				&& frm.doc.receipt_payer_currency
				&& frm.doc.receipt_payer_currency === row.receipt_currency
				&& Number(frm.doc.receipt_payer_exchange_rate) > 0
			) {
				// Default-only: a row Rate the user already entered manually is never
				// overwritten, and other foreign currencies keep their own rate.
				await frappe.model.set_value(cdt, cdn, "credit_exchange_rate", frm.doc.receipt_payer_exchange_rate);
			}
			if (row.credit_account) {
				const details = await getAccountDetailsSafely(row.credit_account, frm.doc.company);
				if (details && details.account_currency !== row.receipt_currency) {
					await frappe.model.set_value(cdt, cdn, "credit_account", "");
				}
			}
			await this.suggestReceiptAccount(frm, cdt, cdn);
			await this.calculate(frm, cdt, cdn, "credit");
		} finally {
			receiptForm.configureGrid(frm, true);
			receiptForm.renderSummary(frm);
		}
	},
	async suggestReceiptAccount(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (
			row.credit_account
			|| row.receipt_recipient_type === ACCOUNT_RECIPIENT
			|| row.receipt_recipient_type === BANK_ACCOUNT_RECIPIENT
			|| !row.receipt_recipient_type
			|| !row.receipt_recipient
			|| !row.receipt_currency
			|| !frm.doc.company
		) {
			return;
		}
		const account = await getReceiptSuggestionSafely(
			row.receipt_recipient_type,
			row.receipt_recipient,
			frm.doc.company,
			row.receipt_currency,
		);
		if (account && !row.credit_account) {
			await frappe.model.set_value(cdt, cdn, "credit_account", account);
		}
	},
	async copyPreviousReceiptRow(frm, cdt, cdn) {
		if (frm.doc.operation_type !== RECEIPT) {
			return;
		}
		const rows = frm.doc.operational_pairs || [];
		const index = rows.findIndex((candidate) => candidate.name === cdn);
		if (index < 1) {
			await frappe.model.set_value(cdt, cdn, "receipt_posting_date", frm.doc.posting_date || "");
			receiptForm.configureGrid(frm, true);
			return;
		}
		const row = locals[cdt][cdn];
		const previous = rows[index - 1];
		row.__sp_receipt_copying = true;
		try {
			for (const fieldname of [
				"receipt_posting_date",
				"receipt_recipient_type",
				"receipt_recipient",
				"receipt_currency",
				"credit_account",
				"credit_exchange_rate",
			]) {
				const value = fieldname === "receipt_posting_date"
					? previous[fieldname] || frm.doc.posting_date || ""
					: previous[fieldname] || "";
				await frappe.model.set_value(cdt, cdn, fieldname, value);
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
	operational_pairs_remove(frm) {
		if (frm.doc.operation_type === RECEIPT) {
			receiptForm.configureGrid(frm, true);
			receiptForm.renderSummary(frm);
		}
	},
	receipt_recipient_type(frm, cdt, cdn) {
		return spAccountingPair.rowTypeChanged(frm, cdt, cdn);
	},
	receipt_recipient(frm, cdt, cdn) {
		return spAccountingPair.rowPartyChanged(frm, cdt, cdn);
	},
	receipt_currency(frm, cdt, cdn) {
		return spAccountingPair.rowCurrencyChanged(frm, cdt, cdn);
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
