// Persian wording per operation type. Receipt: header = receiver, rows = payers.
// Payment mirrors it: header = payer, rows = recipients. Receipt header labels
// stay the DocType metadata; Payment relabels the same fields on its own form.
const spFlowText = {
	Receipt: {
		sections: { pairs_section: "ردیف‌های دریافت", operational_pairs: "پرداخت‌کنندگان / منابع" },
		header: {},
		rows: { receipt_recipient_type: "نوع پرداخت‌کننده", receipt_recipient: "پرداخت‌کننده", account: "معین پرداخت‌کننده" },
		summaryTitle: "مجموع واریزی به دریافت‌کننده",
		headerCurrency: "ارز دریافت‌کننده",
		headerAmount: "مبلغ دریافت‌کننده",
		incomplete: "رسید کامل نیست",
		currencyChange:
			"ارز پرداخت‌کننده از {0} به {1} تغییر می‌کند. پرداخت‌کننده، معین و نرخ ارز {2} ردیفِ پرشده با ارز قبلی پاک می‌شود؛ نوع پرداخت‌کننده، مبلغ و تاریخ ردیف‌ها می‌ماند. ادامه می‌دهید؟",
		preview: "receipt_api.preview_receipt",
	},
	Payment: {
		sections: { pairs_section: "ردیف‌های پرداخت", operational_pairs: "دریافت‌کنندگان / مصارف" },
		header: {
			receipt_receiver_kind: "نوع پرداخت‌کننده",
			receipt_payer_currency: "ارز پرداخت‌کننده",
			receipt_bank_account: "پرداخت‌کننده",
			receipt_payer: "پرداخت‌کننده",
			receipt_payer_account: "معین پرداخت‌کننده",
			receipt_payer_exchange_rate: "نرخ ارز پرداخت‌کننده",
			receipt_credit_currency: "ارز دریافت‌کننده",
			receipt_summary: "خلاصه پرداخت",
		},
		rows: { receipt_recipient_type: "نوع دریافت‌کننده", receipt_recipient: "دریافت‌کننده", account: "معین دریافت‌کننده" },
		summaryTitle: "مجموع برداشت از پرداخت‌کننده",
		headerCurrency: "ارز پرداخت‌کننده",
		headerAmount: "مبلغ پرداخت‌کننده",
		incomplete: "پرداخت کامل نیست",
		currencyChange:
			"ارز دریافت‌کننده از {0} به {1} تغییر می‌کند. دریافت‌کننده، معین و نرخ ارز {2} ردیفِ پرشده با ارز قبلی پاک می‌شود؛ نوع دریافت‌کننده، مبلغ و تاریخ ردیف‌ها می‌ماند. ادامه می‌دهید؟",
		preview: "payment_api.preview_payment",
	},

	of(doc) {
		return this[doc?.operation_type] || this.Receipt;
	},

	// Every field Payment relabels; Receipt restores their DocType labels.
	headerLabels(doc, baseLabel) {
		const own = this.of(doc).header;
		const labels = {};
		for (const fieldname of Object.keys(this.Payment.header)) {
			const label = own[fieldname] ?? baseLabel(fieldname);
			if (label) {
				labels[fieldname] = label;
			}
		}
		return labels;
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = spFlowText;
}
