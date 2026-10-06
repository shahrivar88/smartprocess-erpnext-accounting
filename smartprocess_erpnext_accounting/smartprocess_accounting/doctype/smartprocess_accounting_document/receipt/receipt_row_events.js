// Row events = the row side (Receipt payers, Payment recipients). Every row
// inherits the header row currency and keeps its own rate: Type → Party →
// Ledger Account → Amount → Rate. Base Amount comes from the server preview.
// Field changes never validate or show messages; Add Row / Save do that.
const SP_RECEIPT_COPIED_FIELDS = ["exchange_rate", "receipt_recipient_type", "receipt_recipient", "account"];

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

	// A filled row keeps a stored currency that disagrees with the header, so
	// the server reports it instead of the form silently rewriting it.
	async applyDefaults(frm, row) {
		const defaultType = spReceiptForm.state(frm).payerTypeDefault;
		if (!row.receipt_recipient_type && defaultType) {
			await this.setRowValue(row, "receipt_recipient_type", defaultType);
		}
		const currency = frm.doc[spReceiptConfig.PAYER_CURRENCY];
		const filled = spReceiptValidation.rowHasUserContent(row, frm.doc);
		if (currency && (!row.receipt_currency || !filled)) {
			await this.setRowValue(row, "receipt_currency", currency);
		}
		if (!row.receipt_posting_date && !filled && frm.doc.posting_date) {
			await this.setRowValue(row, "receipt_posting_date", frm.doc.posting_date);
		}
		await this.normalizeRate(frm, row, false);
	},

	// A base Payer Currency always uses rate 1. A rate entered for another
	// currency is dropped; otherwise each row keeps its own manual rate. An
	// empty row in the header currency starts from the header rate.
	async normalizeRate(frm, row, reset) {
		const rate = spReceiptConfig.rowField(frm.doc, "exchange_rate");
		if (spReceiptConfig.isBasePayer(frm.doc)) {
			if (Number(row[rate]) !== 1) {
				await this.setRowValue(row, rate, 1);
			}
			return;
		}
		if (reset && row[rate]) {
			await this.setRowValue(row, rate, null);
		}
		const headerRate = frm.doc.receipt_payer_exchange_rate;
		if (!row[rate] && headerRate && spReceiptConfig.isSameCurrency(frm.doc)) {
			await this.setRowValue(row, rate, headerRate);
		}
	},

	applyCurrencyOptions(frm, values) {
		const grid = frm.fields_dict[spReceiptConfig.TABLE]?.grid;
		if (!grid) {
			return;
		}
		const used = [frm.doc[spReceiptConfig.PAYER_CURRENCY], ...this.rows(frm).map((row) => row.receipt_currency)];
		const options = [...new Set([...values, ...used].filter(Boolean))].join("\n");
		spReceiptForm.setGridProperty(frm, grid, "receipt_currency", "options", options);
	},

	// Payers, ledgers and rates belong to one currency; a row that already
	// carries another currency loses only those values.
	isIncompatible(row, currency) {
		return Boolean(row.receipt_currency && row.receipt_currency !== currency);
	},

	rowsLosingValues(frm, currency) {
		const account = spReceiptConfig.rowField(frm.doc, "account");
		const rate = spReceiptConfig.rowField(frm.doc, "exchange_rate");
		return this.rows(frm).filter((row) =>
			this.isIncompatible(row, currency)
			&& (row.receipt_recipient || row[account] || (row[rate] && Number(row[rate]) !== 1)),
		);
	},

	async syncPayerCurrency(frm) {
		if (frm.doc.docstatus !== 0) {
			return;
		}
		const currency = frm.doc[spReceiptConfig.PAYER_CURRENCY] || "";
		await spReceiptForm.quietly(frm, async () => {
			for (const row of this.rows(frm)) {
				const incompatible = this.isIncompatible(row, currency);
				if (incompatible) {
					await this.setRowValue(row, "receipt_recipient", "");
					await this.setRowValue(row, spReceiptConfig.rowField(frm.doc, "account"), "");
				}
				await this.setRowValue(row, "receipt_currency", currency);
				await this.normalizeRate(frm, row, incompatible);
			}
		});
	},

	// Rows created later take the document date; existing rows keep theirs.
	async postingDateChanged(frm, previous) {
		const date = frm.doc.posting_date || "";
		const kept = [];
		await spReceiptForm.quietly(frm, async () => {
			for (const row of this.rows(frm)) {
				if (!row.receipt_posting_date || row.receipt_posting_date === date) {
					continue;
				}
				if (!spReceiptValidation.rowHasUserContent(row, frm.doc) && row.receipt_posting_date === previous) {
					await this.setRowValue(row, "receipt_posting_date", date);
				} else {
					kept.push(row);
				}
			}
		});
		return kept;
	},

	async rowAdded(frm, cdt, cdn) {
		if (!spReceiptConfig.isFlow(frm.doc)) {
			return;
		}
		await this.loadPayerTypeSettings(frm);
		const rows = this.rows(frm);
		const index = rows.findIndex((candidate) => candidate.name === cdn);
		const previous = index > 0 ? rows[index - 1] : null;
		const row = frappe.get_doc(cdt, cdn);
		const copied = SP_RECEIPT_COPIED_FIELDS.map((name) => (name.startsWith("receipt_") ? name : spReceiptConfig.rowField(frm.doc, name)));
		await spReceiptForm.quietly(frm, async () => {
			for (const fieldname of previous ? copied : []) {
				if (previous[fieldname]) {
					await this.setRowValue(row, fieldname, previous[fieldname]);
				}
			}
			await this.setRowValue(row, "receipt_posting_date", frm.doc.posting_date || null);
			await this.applyDefaults(frm, row);
		});
		spReceiptSummary.schedule(frm);
	},

	async rateChanged(frm, cdt, cdn) {
		if (!spReceiptConfig.isFlow(frm.doc) || spReceiptForm.isQuiet(frm)) {
			return;
		}
		await spReceiptForm.quietly(frm, () => this.normalizeRate(frm, frappe.get_doc(cdt, cdn), false));
		spReceiptSummary.schedule(frm);
	},

	async payerTypeChanged(frm, cdt, cdn) {
		if (!spReceiptConfig.isFlow(frm.doc) || spReceiptForm.isQuiet(frm)) {
			return;
		}
		const row = frappe.get_doc(cdt, cdn);
		await spReceiptForm.quietly(frm, async () => {
			await this.setRowValue(row, "receipt_recipient", "");
			await this.setRowValue(row, spReceiptConfig.rowField(frm.doc, "account"), "");
		});
		spReceiptSummary.schedule(frm);
	},

	async payerChanged(frm, cdt, cdn) {
		if (!spReceiptConfig.isFlow(frm.doc) || spReceiptForm.isQuiet(frm)) {
			return;
		}
		const row = frappe.get_doc(cdt, cdn);
		const payer = row.receipt_recipient;
		const account = payer ? await this.payerLedger(frm.doc, row) : "";
		if (frappe.get_doc(cdt, cdn)?.receipt_recipient !== payer) {
			return;
		}
		await spReceiptForm.quietly(frm, () => this.setRowValue(row, spReceiptConfig.rowField(frm.doc, "account"), account));
		spReceiptSummary.schedule(frm);
	},

	// Bank Account rows take the Bank Account's own ledger; Party rows use the
	// existing per-currency suggestion. A ledger in another currency is never used.
	async payerLedger(doc, row) {
		const payerType = row.receipt_recipient_type;
		const currency = doc[spReceiptConfig.PAYER_CURRENCY];
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
