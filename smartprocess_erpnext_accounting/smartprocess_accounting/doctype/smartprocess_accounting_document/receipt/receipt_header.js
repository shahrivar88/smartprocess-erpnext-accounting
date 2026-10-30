// Receipt header = Receiver side: Receiver Currency → Type → Receiver → Ledger
// Account → Rate. A ledger whose currency disagrees with the header is rejected.
const SP_RECEIPT_SHARED_LABELS = spFlowText.sharedLabels;
const SP_RECEIVER_FIELDS = ["receipt_bank_account", "receipt_payer", "receipt_payer_account"];

const spReceiptHeader = {
	setupQueries(frm) {
		frm.set_query("receipt_payer_account", () => ({ filters: this.receiverAccountFilters(frm.doc) }));
		frm.set_query("receipt_bank_account", () => this.bankAccountQuery(frm.doc));
		frm.set_query("receipt_payer", () => this.receiverPartyQuery(frm.doc));
	},

	receiverAccountFilters(doc) {
		return spReceiptConfig.accountFilters(
			doc.company,
			doc.receipt_payer_currency,
			spReceiptConfig.receiverAccountType(doc.receipt_receiver_kind),
		);
	},

	bankAccountQuery(doc) {
		return {
			query: spReceiptConfig.method("v2_api.bank_account_query"),
			filters: { company: doc.company, currency: doc.receipt_payer_currency },
		};
	},

	receiverPartyQuery(doc) {
		if (!spReceiptConfig.isFlow(doc)) {
			return {};
		}
		return {
			query: spReceiptConfig.method("v2_api.party_currency_query"),
			filters: {
				party_type: doc.receipt_payer_type,
				company: doc.company,
				currency: doc.receipt_payer_currency,
			},
		};
	},

	configure(frm, isFlow) {
		const labels = isFlow
			? {
				...SP_RECEIPT_SHARED_LABELS.receipt,
				...spFlowText.of(frm.doc).sections,
				...spFlowText.headerLabels(frm.doc, (fieldname) => frappe.meta.docfield_map?.[frm.doctype]?.[fieldname]?.label),
			}
			: SP_RECEIPT_SHARED_LABELS.generic;
		for (const [fieldname, label] of Object.entries(labels)) {
			frm.set_df_property(fieldname, "label", label);
		}
		frm.set_df_property("receipt_payer_exchange_rate", "formatter", isFlow ? spReceiptNumbers.formatter : null);
		this.refreshTitles(frm, labels);
		if (isFlow) {
			this.applyReceiverKindLabels(frm);
		}
	},

	// Only the visible title text is rewritten; layout metadata stays put.
	refreshTitles(frm, labels) {
		const head = frm.fields_dict.pairs_section?.head?.get?.(0);
		const text = head && [...head.childNodes].find((node) => node.nodeType === 3 && node.textContent.trim());
		if (text) text.textContent = ` ${__(labels.pairs_section)} `;
		const title = frm.fields_dict.operational_pairs?.$wrapper?.find?.(".grid-field > .control-label").first();
		if (title?.length) title.text(__(labels.operational_pairs));
	},

	applyReceiverKindLabels(frm) {
		const df = frm.fields_dict.receipt_receiver_kind?.df;
		if (!df) {
			return;
		}
		const schema = Array.isArray(df.options) ? df.options.map((item) => item.value || item).join("\n") : df.options;
		const values = spReceiptConfig.receiverKindValues(schema, frm.doc.receipt_receiver_kind);
		frm.set_df_property(
			"receipt_receiver_kind",
			"options",
			values.map((value) => ({ value, label: spReceiptConfig.RECEIVER_KIND_LABELS[value] || value })),
		);
	},

	async initialize(frm) {
		if (frm.doc.docstatus !== 0) {
			this.applyCurrencyOptions(frm, []);
			return;
		}
		await this.ensureReceiverKind(frm);
		await this.ensureCompanyCurrency(frm);
		await this.loadCurrencyOptions(frm);
		await this.applyDefaultCurrency(frm, false);
		await this.normalizeRate(frm, false);
		await spReceiptPayerHeader.applyDefault(frm, false);
	},

	async ensureReceiverKind(frm) {
		const kind = frm.doc.receipt_receiver_kind || frm.fields_dict.receipt_receiver_kind?.df?.default || "";
		if (frm.doc.receipt_receiver_kind !== kind) {
			await frm.set_value("receipt_receiver_kind", kind);
		}
		const partyType = spReceiptConfig.isPartyType(kind) ? kind : "";
		if ((frm.doc.receipt_payer_type || "") !== partyType) {
			await frm.set_value("receipt_payer_type", partyType);
		}
	},

	async ensureCompanyCurrency(frm) {
		if (!frm.doc.company || frm.doc.company_currency) {
			return;
		}
		const currency = await frappe.xcall(spReceiptConfig.method("v2_api.get_company_currency"), {
			company: frm.doc.company,
		});
		await frm.set_value("company_currency", currency || "");
	},

	async loadCurrencyOptions(frm) {
		const state = spReceiptForm.state(frm);
		const company = frm.doc.company;
		if (!company) {
			this.applyCurrencyOptions(frm, []);
			return;
		}
		if (state.currencyOptions?.company !== company) {
			const values = await frappe.xcall(
				spReceiptConfig.method("v2_api.get_receipt_currency_options"),
				{ company },
				"GET",
			);
			state.currencyOptions = { company, values: values || [] };
		}
		this.applyCurrencyOptions(frm, state.currencyOptions.values);
	},

	applyCurrencyOptions(frm, values) {
		for (const fieldname of ["receipt_payer_currency", spReceiptConfig.PAYER_CURRENCY]) {
			const options = [...new Set([...values, frm.doc[fieldname]].filter(Boolean))].join("\n");
			if (frm.fields_dict[fieldname]?.df?.options !== options) {
				frm.set_df_property(fieldname, "options", options);
			}
		}
		spReceiptRowEvents.applyCurrencyOptions(frm, values);
	},

	hasReceiptData(doc) {
		return SP_RECEIVER_FIELDS.some((fieldname) => doc[fieldname])
			|| (doc[spReceiptConfig.TABLE] || []).some((row) => spReceiptValidation.rowHasUserContent(row, doc));
	},

	async applyDefaultCurrency(frm, replace) {
		const companyCurrency = frm.doc.company_currency;
		if (!companyCurrency || frm.doc.docstatus !== 0) {
			return;
		}
		if (frm.doc.receipt_payer_currency && (!replace || this.hasReceiptData(frm.doc))) {
			return;
		}
		if (frm.doc.receipt_payer_currency !== companyCurrency) {
			this.applyCurrencyOptions(frm, [companyCurrency, ...(spReceiptForm.state(frm).currencyOptions?.values || [])]);
			await frm.set_value("receipt_payer_currency", companyCurrency);
		}
	},

	async normalizeRate(frm, reset) {
		if (frm.doc.docstatus !== 0) {
			return;
		}
		const rate = frm.doc.receipt_payer_exchange_rate;
		if (spReceiptConfig.isBaseCurrency(frm.doc)) {
			if (Number(rate) !== 1) {
				await frm.set_value("receipt_payer_exchange_rate", 1);
			}
			return;
		}
		if (reset && rate) {
			await frm.set_value("receipt_payer_exchange_rate", null);
		}
	},

	async companyChanged(frm) {
		await this.loadCurrencyOptions(frm);
		await this.applyDefaultCurrency(frm, true);
		await this.normalizeRate(frm, false);
		await spReceiptPayerHeader.companyChanged(frm);
		spReceiptSummary.schedule(frm);
	},

	async currencyChanged(frm) {
		const state = spReceiptForm.state(frm);
		const previous = state.currency;
		const current = frm.doc.receipt_payer_currency || "";
		state.currency = current;
		if (previous && previous !== current) {
			await spReceiptForm.quietly(frm, () => this.clearReceiver(frm));
		}
		await this.normalizeRate(frm, previous !== current);
		spReceiptSummary.schedule(frm);
	},

	async clearReceiver(frm) {
		for (const fieldname of SP_RECEIVER_FIELDS) {
			if (frm.doc[fieldname]) {
				await frm.set_value(fieldname, "");
			}
		}
	},

	async receiverKindChanged(frm) {
		if (spReceiptForm.isQuiet(frm)) {
			return;
		}
		const kind = frm.doc.receipt_receiver_kind;
		await spReceiptForm.quietly(frm, async () => {
			await this.clearReceiver(frm);
			const partyType = spReceiptConfig.isPartyType(kind) ? kind : "";
			if ((frm.doc.receipt_payer_type || "") !== partyType) {
				await frm.set_value("receipt_payer_type", partyType);
			}
		});
		spReceiptSummary.schedule(frm);
	},

	async accountChanged(frm) {
		const account = frm.doc.receipt_payer_account;
		const expected = frm.doc.receipt_payer_currency;
		if (!spReceiptForm.isQuiet(frm) && account && expected && frm.doc.company) {
			const details = await frappe.xcall(spReceiptConfig.method("v2_api.get_account_details"), {
				account,
				company: frm.doc.company,
			});
			if (frm.doc.receipt_payer_account !== account) {
				return;
			}
			if (spReceiptConfig.rejectMismatchedAccount(account, details?.account_currency, expected)) {
				await frm.set_value("receipt_payer_account", "");
				return;
			}
		}
		spReceiptSummary.schedule(frm);
	},

	async bankChanged(frm) {
		if (spReceiptForm.isQuiet(frm)) {
			return;
		}
		const bankAccount = frm.doc.receipt_bank_account;
		let account = "";
		if (bankAccount && frm.doc.company) {
			const details = await frappe.xcall(spReceiptConfig.method("v2_api.get_bank_account_details"), {
				bank_account: bankAccount,
				company: frm.doc.company,
			});
			if (frm.doc.receipt_bank_account !== bankAccount) {
				return;
			}
			account = details?.account || "";
			if (spReceiptConfig.rejectMismatchedAccount(account, details?.account_currency, frm.doc.receipt_payer_currency)) {
				account = "";
			}
		}
		await this.setReceiverAccount(frm, account);
	},

	async partyChanged(frm) {
		if (spReceiptForm.isQuiet(frm)) {
			return;
		}
		const party = frm.doc.receipt_payer;
		let account = "";
		if (party && frm.doc.receipt_payer_type && frm.doc.company && frm.doc.receipt_payer_currency) {
			account = await frappe.xcall(spReceiptConfig.method("v2_api.get_receipt_party_account_suggestion"), {
				party_type: frm.doc.receipt_payer_type,
				party,
				company: frm.doc.company,
				currency: frm.doc.receipt_payer_currency,
			});
			if (frm.doc.receipt_payer !== party) {
				return;
			}
		}
		await this.setReceiverAccount(frm, account || "");
	},

	async setReceiverAccount(frm, account) {
		if ((frm.doc.receipt_payer_account || "") !== account) {
			await frm.set_value("receipt_payer_account", account);
		}
		spReceiptSummary.schedule(frm);
	},

	async rateChanged(frm) {
		await this.normalizeRate(frm, false);
		spReceiptSummary.schedule(frm);
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = spReceiptHeader;
}
