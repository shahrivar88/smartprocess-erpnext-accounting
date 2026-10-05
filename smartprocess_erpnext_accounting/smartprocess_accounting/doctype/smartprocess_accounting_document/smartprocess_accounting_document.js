{% include "smartprocess_erpnext_accounting/smartprocess_accounting/doctype/smartprocess_accounting_document/receipt/receipt_config.js" %}
{% include "smartprocess_erpnext_accounting/smartprocess_accounting/doctype/smartprocess_accounting_document/receipt/receipt_numbers.js" %}
{% include "smartprocess_erpnext_accounting/smartprocess_accounting/doctype/smartprocess_accounting_document/receipt/receipt_form.js" %}
{% include "smartprocess_erpnext_accounting/smartprocess_accounting/doctype/smartprocess_accounting_document/receipt/receipt_header.js" %}
{% include "smartprocess_erpnext_accounting/smartprocess_accounting/doctype/smartprocess_accounting_document/receipt/receipt_payer_header.js" %}
{% include "smartprocess_erpnext_accounting/smartprocess_accounting/doctype/smartprocess_accounting_document/receipt/receipt_row_queries.js" %}
{% include "smartprocess_erpnext_accounting/smartprocess_accounting/doctype/smartprocess_accounting_document/receipt/receipt_row_events.js" %}
{% include "smartprocess_erpnext_accounting/smartprocess_accounting/doctype/smartprocess_accounting_document/receipt/receipt_validation_ui.js" %}
{% include "smartprocess_erpnext_accounting/smartprocess_accounting/doctype/smartprocess_accounting_document/receipt/receipt_summary.js" %}

frappe.ui.form.on("SmartProcess Accounting Document", {
	setup(frm) {
		spReceiptForm.setup(frm);
		for (const side of ["debit", "credit"]) {
			frm.set_query(`${side}_account`, "operational_pairs", (doc, cdt, cdn) => {
				const row = frappe.get_doc(cdt, cdn);
				if (side === "credit" && spReceiptConfig.isReceipt(frm.doc)) {
					return { filters: spReceiptRowQueries.payerAccountFilters(frm.doc, row) };
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
				filters: { name: ["in", spReceiptConfig.PARTY_TYPES] },
			}));
		}
	},
	refresh(frm) {
		// Posting units must cancel only through the Receipt's authorized path; keep
		// frappe's linked-docs auto-cancel from cancelling them directly.
		frm.ignore_doctypes_on_cancel_all = ["SmartProcess Accounting Posting"];
		if (canStartCorrection(frm)) {
			frm.add_custom_button(__("Correction"), () => promptForCorrection(frm));
		}
		void spReceiptForm.refresh(frm);
	},
	validate(frm) {
		return spReceiptForm.validate(frm);
	},
	operation_type(frm) {
		return spReceiptForm.refresh(frm);
	},
	async company(frm) {
		const currency = frm.doc.company
			? await frappe.xcall(spReceiptConfig.method("v2_api.get_company_currency"), { company: frm.doc.company })
			: "";
		await frm.set_value("company_currency", currency || "");
		for (const row of frm.doc.operational_pairs || []) {
			await frappe.model.set_value(row.doctype, row.name, "company_currency", currency || "");
		}
		if (spReceiptConfig.isReceipt(frm.doc)) {
			await spReceiptHeader.companyChanged(frm);
		}
	},
	posting_date(frm) {
		return isReceiptForm(frm) && spReceiptPayerHeader.postingDateChanged(frm);
	},
	receipt_payer_currency(frm) {
		return isReceiptForm(frm) && spReceiptHeader.currencyChanged(frm);
	},
	receipt_credit_currency(frm) {
		return isReceiptForm(frm) && spReceiptPayerHeader.currencyChanged(frm);
	},
	receipt_receiver_kind(frm) {
		return isReceiptForm(frm) && spReceiptHeader.receiverKindChanged(frm);
	},
	receipt_bank_account(frm) {
		return isReceiptForm(frm) && spReceiptHeader.bankChanged(frm);
	},
	receipt_payer(frm) {
		return isReceiptForm(frm) && spReceiptHeader.partyChanged(frm);
	},
	receipt_payer_account: receiptPreviewChanged,
	receipt_payer_exchange_rate(frm) {
		return isReceiptForm(frm) && spReceiptHeader.rateChanged(frm);
	},
});

function isReceiptForm(frm) {
	return spReceiptConfig.isReceipt(frm.doc);
}

function receiptPreviewChanged(frm) {
	if (isReceiptForm(frm)) {
		spReceiptSummary.schedule(frm);
	}
}

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

// Generic Payment / Transfer / Conversion pair calculation. Receipt rows never
// use it: their amounts come from the Receipt preview.
const spAccountingPair = {
	async refresh_account(frm, cdt, cdn, side) {
		const row = frappe.get_doc(cdt, cdn);
		const account = row[`${side}_account`];
		if (!account || !frm.doc.company) {
			return;
		}
		const message = await frappe.xcall(spReceiptConfig.method("v2_api.get_account_details"), {
			account,
			company: frm.doc.company,
		});
		await frappe.model.set_value(cdt, cdn, `${side}_account_currency`, message.account_currency);
		await frappe.model.set_value(cdt, cdn, "company_currency", frm.doc.company_currency);
		if (message.account_currency === frm.doc.company_currency) {
			await frappe.model.set_value(cdt, cdn, `${side}_exchange_rate`, 1);
		}
		await this.calculate(frm, cdt, cdn, side);
		await this.suggest(frm, cdt, cdn, side);
	},
	async calculate(frm, cdt, cdn, side) {
		const row = frappe.get_doc(cdt, cdn);
		if (row.__sp_calculating) {
			return;
		}
		row.__sp_calculating = true;
		try {
			const accountCurrency = row[`${side}_account_currency`];
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
		const row = frappe.get_doc(cdt, cdn);
		const partyType = row[`${side}_party_type`];
		const party = row[`${side}_party`];
		const currency = row[`${side}_account_currency`];
		if (!partyType || !party || !frm.doc.company || !currency) {
			return frappe.model.set_value(cdt, cdn, `${side}_suggested_account`, "");
		}
		const message = await frappe.xcall(spReceiptConfig.method("v2_api.get_party_account_suggestion"), {
			party_type: partyType,
			party,
			company: frm.doc.company,
			currency,
		});
		return frappe.model.set_value(cdt, cdn, `${side}_suggested_account`, message || "");
	},
};

const pairEvents = {
	operational_pairs_add(frm, cdt, cdn) {
		return spReceiptRowEvents.rowAdded(frm, cdt, cdn);
	},
	operational_pairs_remove: receiptPreviewChanged,
	receipt_recipient_type(frm, cdt, cdn) {
		return spReceiptRowEvents.payerTypeChanged(frm, cdt, cdn);
	},
	receipt_recipient(frm, cdt, cdn) {
		return spReceiptRowEvents.payerChanged(frm, cdt, cdn);
	},
	receipt_posting_date: receiptPreviewChanged,
	credit_description: receiptPreviewChanged,
};
for (const side of ["debit", "credit"]) {
	const receiptChange = side === "credit" ? receiptPreviewChanged : () => {};
	const receiptRateChange = side === "credit" ? (frm, cdt, cdn) => spReceiptRowEvents.rateChanged(frm, cdt, cdn) : () => {};
	const pick = (receipt, generic) => (frm, cdt, cdn) =>
		isReceiptForm(frm) ? receipt(frm, cdt, cdn) : generic(frm, cdt, cdn);
	pairEvents[`${side}_account`] = pick(receiptChange, (frm, cdt, cdn) => spAccountingPair.refresh_account(frm, cdt, cdn, side));
	pairEvents[`${side}_amount`] = pick(receiptChange, (frm, cdt, cdn) => spAccountingPair.calculate(frm, cdt, cdn, side));
	pairEvents[`${side}_exchange_rate`] = pick(receiptRateChange, (frm, cdt, cdn) => spAccountingPair.calculate(frm, cdt, cdn, side));
	pairEvents[`${side}_party_type`] = pick(() => {}, (frm, cdt, cdn) => spAccountingPair.suggest(frm, cdt, cdn, side));
	pairEvents[`${side}_party`] = pick(() => {}, (frm, cdt, cdn) => spAccountingPair.suggest(frm, cdt, cdn, side));
}
frappe.ui.form.on("SmartProcess Accounting Pair", pairEvents);
