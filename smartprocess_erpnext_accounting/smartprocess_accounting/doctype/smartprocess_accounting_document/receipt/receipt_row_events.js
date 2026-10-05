// Receipt row events = Payer side. Each row has its own Payer Currency and
// rate: Payer Currency → Payer Type → Payer → Payer Ledger Account → Amount →
// Rate. Base Amount comes from the server preview.
// Field changes never validate or show messages; Add Row / Save do that.
const SP_RECEIPT_COPIED_FIELDS = [
	"receipt_posting_date", "receipt_currency", "credit_exchange_rate",
	"receipt_recipient_type", "receipt_recipient", "credit_account",
];

const spReceiptRowEvents = {
	rows(frm) {
		return frm.doc[spReceiptConfig.TABLE] || [];
	},

	async setRowValue(row, fieldname, value) {
		if ((row[fieldname] ?? "") !== (value ?? "")) {
			await frappe.model.set_value(row.doctype, row.name, fieldname, value);
		}
	},

	async initializeRows(frm) {
		if (frm.doc.docstatus !== 0) {
			return;
		}
		await this.loadPayerTypeSettings(frm);
		await spReceiptForm.quietly(frm, async () => {
			for (const row of this.rows(frm)) {
				await this.applyDefaults(frm, row);
			}
		});
	},

	// The default Payer Type, the dropdown order and labels come from
	// SmartProcess Accounting Settings.
	async loadPayerTypeSettings(frm) {
		const state = spReceiptForm.state(frm);
		if (state.payerTypeDefault !== null) {
			return;
		}
		const [defaultType, options] = await Promise.all([
			frappe.xcall(spReceiptConfig.method("v2_api.get_receipt_recipient_type_default"), {}, "GET").catch(() => ""),
			frappe.xcall(spReceiptConfig.method("v2_api.get_receipt_recipient_type_options"), {}, "GET").catch(() => []),
		]);
		state.payerTypeDefault = typeof defaultType === "string" ? defaultType : "";
		state.payerTypeOptions = Array.isArray(options) ? options : [];
	},

	// A new row starts in Company.default_currency; a chosen currency is kept.
	async applyDefaults(frm, row) {
		const defaultType = spReceiptForm.state(frm).payerTypeDefault;
		if (!row.receipt_recipient_type && defaultType) {
			await this.setRowValue(row, "receipt_recipient_type", defaultType);
		}
		if (!row.receipt_currency && frm.doc.company_currency) {
			await this.setRowValue(row, "receipt_currency", frm.doc.company_currency);
		}
		await this.normalizeRate(frm, row, false);
	},

	// Base currency always uses rate 1. A currency change drops a rate that
	// belonged to the previous currency; otherwise a manual rate is kept.
	async normalizeRate(frm, row, reset) {
		if (spReceiptConfig.isBaseRow(frm.doc, row)) {
			if (Number(row.credit_exchange_rate) !== 1) {
				await this.setRowValue(row, "credit_exchange_rate", 1);
			}
		} else if (reset && row.credit_exchange_rate) {
			await this.setRowValue(row, "credit_exchange_rate", null);
		}
	},

	applyCurrencyOptions(frm, values) {
		const grid = frm.fields_dict[spReceiptConfig.TABLE]?.grid;
		if (!grid) {
			return;
		}
		const used = this.rows(frm).map((row) => row.receipt_currency);
		const options = [...new Set([...values, ...used].filter(Boolean))].join("\n");
		spReceiptForm.setGridProperty(frm, grid, "receipt_currency", "options", options);
	},

	// Rows the user has not filled yet follow the new Company currency.
	async companyChanged(frm) {
		if (frm.doc.docstatus !== 0) {
			return;
		}
		await spReceiptForm.quietly(frm, async () => {
			for (const row of this.rows(frm)) {
				if (!spReceiptValidation.rowHasUserContent(row) && frm.doc.company_currency) {
					await this.setRowValue(row, "receipt_currency", frm.doc.company_currency);
				}
				await this.normalizeRate(frm, row, false);
			}
		});
	},

	async rowAdded(frm, cdt, cdn) {
		if (!spReceiptConfig.isReceipt(frm.doc)) {
			return;
		}
		await this.loadPayerTypeSettings(frm);
		const rows = this.rows(frm);
		const index = rows.findIndex((candidate) => candidate.name === cdn);
		const previous = index > 0 ? rows[index - 1] : null;
		const row = frappe.get_doc(cdt, cdn);
		await spReceiptForm.quietly(frm, async () => {
			for (const fieldname of previous ? SP_RECEIPT_COPIED_FIELDS : []) {
				if (previous[fieldname]) {
					await this.setRowValue(row, fieldname, previous[fieldname]);
				}
			}
			await this.applyDefaults(frm, row);
		});
		spReceiptSummary.schedule(frm);
	},

	// Payer and ledger lists are filtered by the row currency, so they reset.
	async currencyChanged(frm, cdt, cdn) {
		if (!spReceiptConfig.isReceipt(frm.doc) || spReceiptForm.isQuiet(frm)) {
			return;
		}
		const row = frappe.get_doc(cdt, cdn);
		await spReceiptForm.quietly(frm, async () => {
			await this.setRowValue(row, "receipt_recipient", "");
			await this.setRowValue(row, "credit_account", "");
			await this.normalizeRate(frm, row, true);
		});
		spReceiptSummary.schedule(frm);
	},

	async rateChanged(frm, cdt, cdn) {
		if (!spReceiptConfig.isReceipt(frm.doc) || spReceiptForm.isQuiet(frm)) {
			return;
		}
		await spReceiptForm.quietly(frm, () => this.normalizeRate(frm, frappe.get_doc(cdt, cdn), false));
		spReceiptSummary.schedule(frm);
	},

	async payerTypeChanged(frm, cdt, cdn) {
		if (!spReceiptConfig.isReceipt(frm.doc) || spReceiptForm.isQuiet(frm)) {
			return;
		}
		const row = frappe.get_doc(cdt, cdn);
		await spReceiptForm.quietly(frm, async () => {
			await this.setRowValue(row, "receipt_recipient", "");
			await this.setRowValue(row, "credit_account", "");
		});
		spReceiptSummary.schedule(frm);
	},

	async payerChanged(frm, cdt, cdn) {
		if (!spReceiptConfig.isReceipt(frm.doc) || spReceiptForm.isQuiet(frm)) {
			return;
		}
		const row = frappe.get_doc(cdt, cdn);
		const payer = row.receipt_recipient;
		const account = payer ? await this.payerLedger(frm.doc, row) : "";
		if (frappe.get_doc(cdt, cdn)?.receipt_recipient !== payer) {
			return;
		}
		await spReceiptForm.quietly(frm, () => this.setRowValue(row, "credit_account", account));
		spReceiptSummary.schedule(frm);
	},

	// Bank Account rows take the Bank Account's own ledger; Party rows use the
	// existing per-currency suggestion. A ledger in another currency is never used.
	async payerLedger(doc, row) {
		const payerType = row.receipt_recipient_type;
		const currency = row.receipt_currency;
		if (!doc.company || !currency) {
			return "";
		}
		if (payerType === spReceiptConfig.BANK_ACCOUNT_PAYER) {
			const details = await frappe.xcall(spReceiptConfig.method("v2_api.get_bank_account_details"), {
				bank_account: row.receipt_recipient,
				company: doc.company,
			});
			return details?.account_currency === currency ? details.account : "";
		}
		if (spReceiptConfig.isPartyType(payerType)) {
			const account = await frappe.xcall(
				spReceiptConfig.method("v2_api.get_receipt_party_account_suggestion"),
				{ party_type: payerType, party: row.receipt_recipient, company: doc.company, currency },
			);
			return account || "";
		}
		return "";
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = spReceiptRowEvents;
}
