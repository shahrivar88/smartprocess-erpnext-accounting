// Receipt client constants. Values mirror receipt_contract.py on the server.
const spReceiptConfig = {
	OPERATION: "Receipt",
	PAYMENT: "Payment",
	// Receipt rows are the credited payers; Payment rows are the debited recipients.
	ROW_SIDES: { Receipt: "credit", Payment: "debit" },
	CHILD_DOCTYPE: "SmartProcess Accounting Pair",
	TABLE: "operational_pairs",
	ACCOUNT_PAYER: "Account",
	BANK_ACCOUNT_PAYER: "Bank Account",
	BANK_RECEIVER: "بانک",
	OTHER_RECEIVER: "سایر حساب‌ها",
	PARTY_TYPES: ["Customer", "Supplier", "Employee", "SmartProcess Financial Intermediary", "Shareholder"],
	RECEIVER_ACCOUNT_TYPES: { "بانک": "Bank", "صندوق": "Cash" },
	PARTY_ACCOUNT_TYPES: {
		Customer: "Receivable",
		"SmartProcess Financial Intermediary": "Receivable",
		Supplier: "Payable",
		Employee: "Payable",
		Shareholder: "Payable",
	},
	NON_GENERIC_ACCOUNT_TYPES: ["Bank", "Cash", "Receivable", "Payable"],
	// Display labels only; stored values stay the native Party Type names.
	RECEIVER_KIND_LABELS: {
		Customer: "مشتری",
		Supplier: "تامین‌کننده",
		"SmartProcess Financial Intermediary": "واسطه مالی",
		Employee: "کارمند",
		Shareholder: "سهامدار",
	},
	API: "smartprocess_erpnext_accounting.smartprocess_accounting",
	PAYER_CURRENCY: "receipt_credit_currency",
	// Grid rows evaluate this with the row as doc and the Receipt as parent.
	ROW_BASE_RATE: "eval:parent.receipt_credit_currency && parent.company_currency && parent.receipt_credit_currency == parent.company_currency",

	method(path) {
		return `${this.API}.${path}`;
	},

	isReceipt(doc) {
		return doc?.operation_type === this.OPERATION;
	},

	isPayment(doc) {
		return doc?.operation_type === this.PAYMENT;
	},

	// Receipt and Payment share this client: one header side, rows on the other.
	// A Payment submitted before Payment V1 has no header account; it keeps the
	// generic two-sided grid so none of its stored columns are hidden.
	isFlow(doc) {
		if (this.isPayment(doc) && doc.docstatus > 0 && !doc.receipt_payer_account) {
			return false;
		}
		return Boolean(this.ROW_SIDES[doc?.operation_type]);
	},

	// Schema still stores Transfer / Currency Conversion for history.
	// New documents only offer the live Receipt and Payment operations.
	ACTIVE_OPERATIONS: ["Receipt", "Payment"],

	operationTypeOptions(doc) {
		const current = doc?.operation_type || "";
		if (!current || this.ACTIVE_OPERATIONS.includes(current)) {
			return this.ACTIVE_OPERATIONS.join("\n");
		}
		return `${this.ACTIVE_OPERATIONS.join("\n")}\n${current}`;
	},

	rowSide(doc) {
		return this.ROW_SIDES[doc?.operation_type] || this.ROW_SIDES.Receipt;
	},

	rowField(doc, name) {
		return `${this.rowSide(doc)}_${name}`;
	},

	isPartyType(type) {
		return this.PARTY_TYPES.includes(type);
	},

	shareholderInDocuments() {
		const flags = (typeof frappe !== "undefined" && frappe.boot?.smartprocess_accounting?.shareholder_accounting) || {};
		return Boolean(Number(flags.enabled) && Number(flags.show_in_smart_document));
	},

	documentPartyTypes() {
		if (this.shareholderInDocuments()) {
			return this.PARTY_TYPES;
		}
		return this.PARTY_TYPES.filter((name) => name !== "Shareholder");
	},

	receiverKindValues(schemaOptions, current) {
		const values = String(schemaOptions || "").split("\n").filter(Boolean);
		const enabled = this.shareholderInDocuments();
		const has = values.includes("Shareholder");
		if (enabled && !has) {
			const at = values.indexOf("Employee");
			values.splice(at >= 0 ? at + 1 : values.length, 0, "Shareholder");
		}
		if (!enabled && has && current !== "Shareholder") {
			return values.filter((name) => name !== "Shareholder");
		}
		return values;
	},

	isBase(currency, companyCurrency) {
		return Boolean(currency && currency === companyCurrency);
	},

	isForeign(currency, companyCurrency) {
		return Boolean(currency && companyCurrency && currency !== companyCurrency);
	},

	// The header currency is the Receiver currency.
	isBaseCurrency(doc) {
		return this.isBase(doc.receipt_payer_currency, doc.company_currency);
	},

	isForeignCurrency(doc) {
		return this.isForeign(doc.receipt_payer_currency, doc.company_currency);
	},

	// Every row uses the one header Payer Currency.
	isBasePayer(doc) {
		return this.isBase(doc.receipt_credit_currency, doc.company_currency);
	},

	isForeignPayer(doc) {
		return this.isForeign(doc.receipt_credit_currency, doc.company_currency);
	},

	// Same header and row currency: every Pair uses the one header rate.
	isSameCurrency(doc) {
		return Boolean(doc.receipt_payer_currency && doc.receipt_payer_currency === doc.receipt_credit_currency);
	},

	// Frappe ignores an empty filter, so a missing currency must not list every Account.
	NO_ACCOUNT_CURRENCY: "__none__",

	accountCurrencyMismatch(account, actual, expected) {
		return __("ارز حساب معین «{0}» {1} است؛ باید با ارز تراکنش ({2}) یکی باشد. برای این ارز، حساب معین جداگانه‌ای انتخاب کنید.", [
			account,
			actual,
			expected,
		]);
	},

	rejectMismatchedAccount(account, actual, expected) {
		if (!account || !actual || !expected || actual === expected) {
			return false;
		}
		frappe.msgprint({
			title: __("ارز حساب معین"),
			message: this.accountCurrencyMismatch(account, actual, expected),
			indicator: "red",
		});
		return true;
	},

	// Every ledger is in its own side's currency (Receiver or Payer);
	// an empty currency matches nothing instead of widening the list.
	accountFilters(company, currency, accountType) {
		const filters = {
			company: company || "",
			disabled: 0,
			is_group: 0,
			account_currency: currency || this.NO_ACCOUNT_CURRENCY,
		};
		if (accountType) {
			filters.account_type = accountType;
		}
		return filters;
	},

	receiverAccountType(receiverKind) {
		if (this.RECEIVER_ACCOUNT_TYPES[receiverKind]) {
			return this.RECEIVER_ACCOUNT_TYPES[receiverKind];
		}
		if (receiverKind === this.OTHER_RECEIVER) {
			return ["not in", this.NON_GENERIC_ACCOUNT_TYPES];
		}
		return this.PARTY_ACCOUNT_TYPES[receiverKind] || null;
	},

	payerAccountType(payerType) {
		if (payerType === this.BANK_ACCOUNT_PAYER) {
			return "Bank";
		}
		if (payerType === this.ACCOUNT_PAYER) {
			return ["not in", ["Receivable", "Payable"]];
		}
		return this.PARTY_ACCOUNT_TYPES[payerType] || null;
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = spReceiptConfig;
}
