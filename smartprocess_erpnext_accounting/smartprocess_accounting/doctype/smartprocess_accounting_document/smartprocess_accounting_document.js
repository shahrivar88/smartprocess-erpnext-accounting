const RECEIPT = "Receipt";
const ACCOUNT_RECIPIENT = "Account";
const PARTY_TYPES = ["Customer", "Supplier", "Employee", "SmartProcess Financial Intermediary"];
const RECEIPT_RECIPIENT_TYPES = [...PARTY_TYPES, ACCOUNT_RECIPIENT];
const RECEIPT_FIELDS = [
	"receipt_posting_date",
	"receipt_recipient_type",
	"receipt_recipient",
	"receipt_currency",
];
const TECHNICAL_RECEIPT_FIELDS = [
	"debit_account_category",
	"debit_suggested_account",
	"debit_party_type",
	"debit_party",
	"debit_account_currency",
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
const RECEIPT_NUMBER_FIELDS = ["debit_amount", "debit_exchange_rate", "debit_company_amount"];

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
		if (canStartCorrection(frm)) {
			frm.add_custom_button(__("Correction"), () => promptForCorrection(frm));
		}
		receiptForm.configure(frm);
		void receiptForm.loadCurrencyOptions(frm);
	},
	setup(frm) {
		frm.set_query("receipt_payer_type", () => ({ filters: { name: ["in", PARTY_TYPES] } }));
		frm.set_query("receipt_recipient_type", "operational_pairs", () => ({
			filters: { name: ["in", RECEIPT_RECIPIENT_TYPES] },
		}));
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
		return receiptForm.loadCurrencyOptions(frm);
	},
	posting_date(frm) {
		return receiptForm.parentPostingDateChanged(frm);
	},
	async company(frm) {
		if (!frm.doc.company) {
			await frm.set_value("company_currency", "");
			if (frm.doc.operation_type === RECEIPT) {
				await frm.set_value("receipt_payer_account", "");
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
				await frappe.model.set_value(row.doctype, row.name, "debit_account", "");
			}
		}
		if (frm.doc.operation_type === RECEIPT) {
			await frm.set_value("receipt_payer_account", "");
			await receiptForm.loadCurrencyOptions(frm, true);
			await receiptForm.payerCurrencyChanged(frm);
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
	receipt_payer_exchange_rate(frm) {
		return receiptForm.payerRateChanged(frm);
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
	const columns = [
		["receipt_posting_date", 1],
		["receipt_recipient_type", 1],
	];
	if (hasPartyRecipient) {
		columns.push(["receipt_recipient", 2]);
	}
	columns.push(
		["receipt_currency", 1],
		["debit_account", 2],
		["debit_amount", 1],
	);
	if (hasForeign) {
		columns.push(["debit_exchange_rate", 1], ["debit_company_amount", 1]);
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
		this.configureHeader(frm, isReceipt);
		this.configureGrid(frm, isReceipt);
		if (isReceipt && frm.__sp_previous_payer_currency === undefined) {
			frm.__sp_previous_payer_currency = frm.doc.receipt_payer_currency || "";
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
		const foreignPayer = isReceipt
			&& frm.doc.receipt_payer_currency
			&& frm.doc.receipt_payer_currency !== frm.doc.company_currency;
		frm.toggle_display("receipt_payer_exchange_rate", Boolean(foreignPayer));
		frm.toggle_reqd("receipt_payer_exchange_rate", Boolean(foreignPayer));
		frm.set_df_property(
			"receipt_payer_exchange_rate",
			"formatter",
			isReceipt ? compactNumberFormatter : null,
		);
		if (isReceipt) {
			configureCompactNumberInput(frm.fields_dict.receipt_payer_exchange_rate);
		}
		this.updatePayerRateMeaning(frm);
		frm.toggle_display("company_currency", !isReceipt);
	},
	configureGrid(frm, isReceipt) {
		const grid = frm.fields_dict.operational_pairs?.grid;
		if (!grid) {
			return;
		}
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
		grid.set_column_disp_in_list_view(TECHNICAL_RECEIPT_FIELDS, !isReceipt);
		grid.set_column_disp_in_list_view(["debit_account", "debit_amount"], true);
		grid.toggle_display("receipt_payer_exchange_rate", false);
		grid.set_column_disp_in_list_view("receipt_payer_exchange_rate", false);
		grid.toggle_display("debit_description", true);
		grid.toggle_display("debit_rate_direction", true);
		grid.set_column_disp_in_list_view(["debit_description", "debit_rate_direction"], false);
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
				...RECEIPT_NUMBER_FIELDS.map((fieldname) => [fieldname, "formatter", null]),
			]);
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
		grid.toggle_display("debit_exchange_rate", hasForeign);
		grid.toggle_display("debit_company_amount", hasForeign);
		grid.set_column_disp_in_list_view("receipt_recipient", hasPartyRecipient);
		grid.set_column_disp_in_list_view("debit_exchange_rate", hasForeign);
		grid.set_column_disp_in_list_view("debit_company_amount", hasForeign);
		const visibleColumns = receiptGridColumns(hasPartyRecipient, hasForeign);
		renderGridProperties(grid, [
			["receipt_recipient_type", "reqd", 1],
			["receipt_currency", "reqd", 1],
			["debit_account", "reqd", 1],
			["debit_amount", "reqd", 1],
			["debit_account", "label", "معین دریافتی"],
			["debit_exchange_rate", "label", "نرخ ارز"],
			["debit_company_amount", "label", "مبلغ به ارز پایه"],
			["debit_rate_direction", "label", "معنی نرخ"],
			["debit_description", "label", "توضیح"],
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
			["receipt_recipient_type", "columns", 1],
			["receipt_recipient", "columns", 2],
			["receipt_currency", "columns", 1],
			["debit_exchange_rate", "columns", 1],
			["debit_company_amount", "columns", 1],
			["debit_account", "columns", 2],
			["debit_amount", "columns", 1],
			...RECEIPT_NUMBER_FIELDS.map((fieldname) => [fieldname, "formatter", compactNumberFormatter]),
			[
				"debit_amount",
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
			["debit_section", "دریافت"],
			["debit_account", "معین دریافتی"],
			["debit_amount", foreign ? "مبلغ ارز" : "مبلغ"],
			["debit_exchange_rate", "نرخ ارز"],
			["debit_company_amount", "مبلغ به ارز پایه"],
			["debit_rate_direction", "معنی نرخ"],
			["debit_description", "توضیح"],
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
		gridRow.toggle_display("receipt_recipient", row.receipt_recipient_type !== ACCOUNT_RECIPIENT);
		gridRow.toggle_display("debit_exchange_rate", hasForeign);
		gridRow.toggle_display("debit_company_amount", hasForeign);
		gridRow.toggle_editable("debit_exchange_rate", Boolean(foreign));
		gridRow.toggle_display("debit_rate_direction", Boolean(foreign));
		gridRow.toggle_display("debit_description", true);
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
		const options = ["", ...new Set([...availableCurrencies, ...storedCurrencies])];
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
		const previousCurrency = frm.__sp_previous_payer_currency || "";
		const currentCurrency = frm.doc.receipt_payer_currency || "";
		frm.__sp_previous_payer_currency = currentCurrency;
		await this.clearMismatchedPayerAccount(frm);
		if (currentCurrency && currentCurrency === frm.doc.company_currency) {
			await frm.set_value("receipt_payer_exchange_rate", 1);
		} else if (currentCurrency !== previousCurrency) {
			await frm.set_value("receipt_payer_exchange_rate", "");
		}
		await this.suggestPayerAccount(frm);
		await this.recalculatePayerRows(frm);
		this.configureHeader(frm, true);
		this.configureGrid(frm, true);
	},
	async payerRateChanged(frm) {
		if (frm.doc.operation_type !== RECEIPT) {
			return;
		}
		if (frm.doc.receipt_payer_currency === frm.doc.company_currency) {
			if (Number(frm.doc.receipt_payer_exchange_rate) !== 1) {
				await frm.set_value("receipt_payer_exchange_rate", 1);
			}
		}
		this.updatePayerRateMeaning(frm);
		await this.recalculatePayerRows(frm);
	},
	updatePayerRateMeaning(frm) {
		const currency = frm.doc.receipt_payer_currency;
		const rate = Number(frm.doc.receipt_payer_exchange_rate || 0);
		const meaning = currency && frm.doc.company_currency && rate > 0
			? `1 ${currency} = ${rate} ${frm.doc.company_currency}`
			: "";
		frm.set_df_property("receipt_payer_exchange_rate", "description", meaning);
	},
	async recalculatePayerRows(frm) {
		for (const row of frm.doc.operational_pairs || []) {
			await spAccountingPair.calculateReceiptPayer(frm, row.doctype, row.name);
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
			if (frm.doc.operation_type === RECEIPT && side === "debit") {
				await this.calculateReceiptPayer(frm, cdt, cdn);
			}
		} finally {
			row.__sp_calculating = false;
		}
	},
	async calculateReceiptPayer(frm, cdt, cdn) {
		if (frm.doc.operation_type !== RECEIPT) {
			return;
		}
		const row = locals[cdt][cdn];
		const companyAmount = Number(row.debit_company_amount || 0);
		const payerCurrency = frm.doc.receipt_payer_currency;
		const basePayer = payerCurrency && payerCurrency === frm.doc.company_currency;
		const payerRate = basePayer ? 1 : Number(frm.doc.receipt_payer_exchange_rate || 0);
		const payerAmount = companyAmount > 0 && payerRate > 0
			? companyAmount / payerRate
			: 0;
		await frappe.model.set_value(cdt, cdn, "credit_account_currency", payerCurrency || "");
		await frappe.model.set_value(cdt, cdn, "credit_exchange_rate", payerRate || "");
		await frappe.model.set_value(cdt, cdn, "credit_amount", payerAmount || "");
		await frappe.model.set_value(cdt, cdn, "credit_company_amount", companyAmount || "");
		const meaning = payerCurrency && frm.doc.company_currency && payerRate > 0
			? `1 ${payerCurrency} = ${payerRate} ${frm.doc.company_currency}`
			: "";
		await frappe.model.set_value(cdt, cdn, "credit_rate_direction", meaning);
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
		receiptForm.configureGrid(frm, true);
		try {
			await frappe.model.set_value(cdt, cdn, "debit_account_currency", row.receipt_currency || "");
			if (changed && !row.__sp_receipt_copying) {
				await frappe.model.set_value(cdt, cdn, "debit_exchange_rate", "");
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
		} finally {
			receiptForm.configureGrid(frm, true);
		}
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
				"debit_account",
				"debit_exchange_rate",
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
		}
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
