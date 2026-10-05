// Receipt row queries: every payer and payer ledger is filtered by the header
// Payer Currency, the company and the row Payer Type.
const spReceiptRowQueries = {
	setupQueries(frm) {
		frm.set_query("receipt_recipient_type", spReceiptConfig.TABLE, () => ({
			query: spReceiptConfig.method("v2_api.receipt_recipient_type_query"),
		}));
		frm.set_query("receipt_recipient", spReceiptConfig.TABLE, (doc, cdt, cdn) =>
			this.payerQuery(frm.doc, frappe.get_doc(cdt, cdn)),
		);
	},

	payerQuery(doc, row) {
		if (!spReceiptConfig.isReceipt(doc)) {
			return {};
		}
		const currency = doc[spReceiptConfig.PAYER_CURRENCY];
		const payerType = row?.receipt_recipient_type;
		if (payerType === spReceiptConfig.BANK_ACCOUNT_PAYER) {
			return {
				query: spReceiptConfig.method("v2_api.bank_account_query"),
				filters: { company: doc.company, currency },
			};
		}
		if (spReceiptConfig.isPartyType(payerType)) {
			return {
				query: spReceiptConfig.method("v2_api.party_currency_query"),
				filters: { party_type: payerType, company: doc.company, currency },
			};
		}
		return {};
	},

	payerAccountFilters(doc, row) {
		return spReceiptConfig.accountFilters(
			doc.company,
			doc[spReceiptConfig.PAYER_CURRENCY],
			spReceiptConfig.payerAccountType(row?.receipt_recipient_type),
		);
	},

	// The Payer Type Link lists DocTypes through search_link, which re-sorts by
	// the translated name; the order and labels configured in SmartProcess
	// Accounting Settings are applied where the list reaches Awesomplete.
	orderPayerTypes(items, options) {
		if (!Array.isArray(items) || !options?.length) {
			return items;
		}
		const rank = new Map(options.map((entry, index) => [entry.value, index]));
		const ranked = [];
		const rest = [];
		for (const item of items) {
			const position = item && typeof item === "object" ? rank.get(item.value) : undefined;
			if (position === undefined) {
				rest.push(item);
				continue;
			}
			item.label = options[position].label;
			item.description = "";
			ranked.push({ position, item });
		}
		ranked.sort((a, b) => a.position - b.position);
		return ranked.map((entry) => entry.item).concat(rest);
	},

	installPayerTypeOrder(frm) {
		const wrapper = frm.fields_dict[spReceiptConfig.TABLE]?.$wrapper?.get(0);
		if (!wrapper || spReceiptOrderedWrappers.has(wrapper)) {
			return;
		}
		spReceiptOrderedWrappers.add(wrapper);
		wrapper.addEventListener("focusin", (event) => {
			const control = spReceiptNumbers.controlFor(event.target, "receipt_recipient_type");
			if (control?.awesomplete && spReceiptConfig.isReceipt(frm.doc)) {
				this.attachPayerTypeOrder(frm, control);
			}
		});
	},

	attachPayerTypeOrder(frm, control) {
		if (spReceiptOrderedControls.has(control)) {
			return;
		}
		spReceiptOrderedControls.add(control);
		const queries = this;
		Object.defineProperty(control.awesomplete, "list", {
			configurable: true,
			enumerable: true,
			get() {
				return this._list;
			},
			set(value) {
				this._list = queries.orderPayerTypes(value, spReceiptForm.state(frm).payerTypeOptions);
			},
		});
	},
};
const spReceiptOrderedWrappers = new WeakSet();
const spReceiptOrderedControls = new WeakSet();

if (typeof module === "object" && module.exports) {
	module.exports = spReceiptRowQueries;
}
