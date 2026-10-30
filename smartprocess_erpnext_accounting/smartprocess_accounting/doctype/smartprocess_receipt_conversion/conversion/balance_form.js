// Balance Conversion form: the server returns the balance, the maximum and the Target Amount.
const spBalanceForm = {
	MODE: "Balance",
	DELAY: 300,
	SOURCE_FIELDS: ["source_party_type", "source_party", "source_account"],
	NUMBER_FIELDS: ["conversion_amount", "target_rate"],
	MODE_LABELS: { Receipt: "از رسید", Balance: "از مانده حساب" },
	BALANCE_SIDE_LABELS: { Debit: "بدهکار", Credit: "بستانکار" },
	MESSAGES: {
		legsLabel: "تخصیص‌های داخلی (فقط برای حسابرسی)",
		currencyKept: "ارز پیشنهادی این طرف حساب {0} است. ارز مقصد انتخاب‌شده ({1}) تغییر نکرد.",
		partial:
			"بخشی از مانده حساب از اسنادی است که فعلاً قابل تبدیل نیستند (مثل اسناد استاندارد ERPNext یا سند ثبت مبهم). فقط «حداکثر قابل تبدیل» قابل تبدیل است.",
	},

	isBalance(frm) {
		return frm.doc.conversion_mode === this.MODE;
	},

	state(frm) {
		if (frm.__sp_balance?.doc !== frm.doc) {
			frm.__sp_balance = { doc: frm.doc, timer: null, summaryRequest: 0, previewRequest: 0, prefilling: false };
		}
		return frm.__sp_balance;
	},

	companyCurrency(frm) {
		return frm.doc.source_currency || spConversionForm.state(frm).companyCurrency || "";
	},

	setup(frm) {
		const legs = spConversionLegs;
		const partyTypes = () => ({ filters: { name: ["in", legs.documentPartyTypes()] } });
		const parties = (partyType, currency) => ({
			query: legs.method(spConversionForm.PARTY_QUERY),
			filters: { party_type: partyType, company: frm.doc.company, currency },
		});
		frm.set_query("source_party_type", partyTypes);
		frm.set_query("target_party_type", partyTypes);
		frm.set_query("source_party", (doc) => parties(doc.source_party_type, this.companyCurrency(frm)));
		frm.set_query("target_party", (doc) => parties(doc.target_party_type, doc.target_currency));
		frm.set_query("source_account", (doc) => ({
			filters: legs.accountFilters(doc.company, this.companyCurrency(frm), doc.source_party_type, doc.source_party),
		}));
		frm.set_query("target_account", (doc) => ({
			filters: legs.accountFilters(doc.company, doc.target_currency, doc.target_party_type, doc.target_party),
		}));
	},

	refresh(frm) {
		frm.set_df_property("conversion_mode", "options", this.selectOptions(this.MODE_LABELS));
		frm.set_df_property("balance_side", "options", [{ value: "", label: "" }, ...this.selectOptions(this.BALANCE_SIDE_LABELS)]);
		if (!this.isBalance(frm)) {
			return;
		}
		frm.set_df_property(spConversionLegs.TABLE, "label", this.MESSAGES.legsLabel);
		frm.set_df_property(spConversionLegs.TABLE, "read_only", 1);
		for (const fieldname of this.NUMBER_FIELDS) {
			spReceiptNumbers.prepare(frm, frm.fields_dict[fieldname], spConversionForm.numberOptions(frm));
		}
		this.showDifference(frm);
		if (frm.doc.docstatus === 0) {
			return this.loadSummary(frm);
		}
	},

	selectOptions(labels) {
		return Object.entries(labels).map(([value, label]) => ({ value, label }));
	},

	modeChanged(frm) {
		if (!this.isBalance(frm)) {
			return;
		}
		frm.doc.source_receipt = null;
		frm.clear_table(spConversionLegs.TABLE);
		return this.refresh(frm);
	},

	async sourcePartyTypeChanged(frm) {
		if (frm.doc.source_party) {
			await frm.set_value("source_party", "");
		}
		this.scheduleSummary(frm);
	},

	// Prefills the native Party Account mapping only into an empty Account.
	async sourcePartyChanged(frm) {
		const doc = frm.doc;
		if (doc.source_party && !doc.source_account && this.companyCurrency(frm)) {
			const account = await this.partyAccount(frm, doc.source_party_type, doc.source_party, this.companyCurrency(frm));
			if (account && !frm.doc.source_account) {
				return frm.set_value("source_account", account);
			}
		}
		this.scheduleSummary(frm);
	},

	async targetPartyTypeChanged(frm) {
		if (!this.state(frm).prefilling && frm.doc.target_party) {
			await frm.set_value("target_party", "");
		}
	},

	async targetPartyChanged(frm) {
		if (this.state(frm).prefilling || !frm.doc.target_party) {
			return;
		}
		await this.suggestTargetCurrency(frm, frm.doc.target_party_type, frm.doc.target_party);
		const doc = frm.doc;
		if (!doc.target_party || doc.target_account || !doc.target_currency) {
			return;
		}
		const account = await this.partyAccount(frm, doc.target_party_type, doc.target_party, doc.target_currency);
		if (account && !frm.doc.target_account) {
			await frm.set_value("target_account", account);
		}
	},

	// A Party with a default currency fills only an empty Target Currency. A chosen
	// currency is kept; the user only gets a note. The rate is never touched.
	async suggestTargetCurrency(frm, partyType, party) {
		if (!partyType || !frm.doc.company) {
			return;
		}
		const currency = await frappe.xcall(
			spConversionLegs.method("v2_api.get_party_suggested_currency"),
			{ party_type: partyType, party, company: frm.doc.company },
			"GET",
		);
		if (!currency || frm.doc.target_party !== party || currency === this.companyCurrency(frm)) {
			return;
		}
		if (!frm.doc.target_currency) {
			await frm.set_value("target_currency", currency);
		} else if (frm.doc.target_currency !== currency) {
			frappe.show_alert({ message: __(this.MESSAGES.currencyKept, [currency, frm.doc.target_currency]), indicator: "orange" });
		}
	},

	partyAccount(frm, partyType, party, currency) {
		return frappe.xcall(spConversionLegs.method("v2_api.get_receipt_party_account_suggestion"), {
			party_type: partyType,
			party,
			company: frm.doc.company,
			currency,
		});
	},

	currencyChanged(frm) {
		this.schedulePreview(frm);
		this.scheduleSummary(frm);
	},

	fillMax(frm) {
		if (frm.doc.docstatus !== 0) {
			return;
		}
		return frm.set_value("conversion_amount", Number(frm.doc.max_convertible) || 0);
	},

	async loadSummary(frm) {
		const state = this.state(frm);
		const doc = frm.doc;
		if (!this.isBalance(frm) || doc.docstatus !== 0) {
			return;
		}
		const request = ++state.summaryRequest;
		if (!doc.company || !this.SOURCE_FIELDS.every((fieldname) => doc[fieldname])) {
			return this.showSummary(frm, null);
		}
		const summary = await frappe.xcall(spConversionLegs.method("balance_conversion_api.get_balance_summary"), {
			company: doc.company,
			source_party_type: doc.source_party_type,
			source_party: doc.source_party,
			source_account: doc.source_account,
			posting_date: doc.posting_date || null,
			target_currency: doc.target_currency || null,
		});
		if (request !== state.summaryRequest || state.doc !== frm.doc) {
			return;
		}
		await this.showSummary(frm, summary);
		if (summary?.suggestion) {
			await this.prefill(frm, summary.suggestion);
		}
	},

	async showSummary(frm, summary) {
		const values = this.summaryValues(summary);
		for (const [fieldname, value] of Object.entries(values)) {
			if ((frm.doc[fieldname] ?? null) !== value) {
				frm.doc[fieldname] = value;
				frm.refresh_field(fieldname);
			}
		}
		frm.set_df_property("source_account", "description", summary?.error ? frappe.utils.escape_html(summary.error) : "");
		this.showDifference(frm);
	},

	summaryValues(summary) {
		const ok = summary && !summary.error;
		const number = (value) => (ok && value !== null && value !== undefined ? Number(value) : null);
		return {
			as_of_balance: number(summary?.as_of_balance),
			balance_side: (ok && summary.balance_side) || "",
			max_convertible: number(summary?.max_convertible),
			...(ok && summary.company_currency ? { source_currency: summary.company_currency } : {}),
		};
	},

	// The balance and the convertible maximum may differ; the form always says so.
	showDifference(frm) {
		const differs = this.differs(frm.doc.as_of_balance, frm.doc.max_convertible);
		frm.set_df_property("max_convertible", "description", differs ? this.MESSAGES.partial : "");
	},

	differs(balance, maximum) {
		return balance !== null && balance !== undefined && maximum !== null && maximum !== undefined && Number(balance) !== Number(maximum);
	},

	// A suggestion fills only an empty target and stays editable.
	async prefill(frm, suggestion) {
		const state = this.state(frm);
		if (frm.doc.target_account || frm.doc.target_party || !suggestion?.target_account) {
			return;
		}
		state.prefilling = true;
		try {
			await frm.set_value({
				target_party_type: suggestion.target_party_type || "",
				target_party: suggestion.target_party || "",
				target_account: suggestion.target_account,
			});
		} finally {
			state.prefilling = false;
		}
	},

	schedulePreview(frm) {
		const state = this.state(frm);
		clearTimeout(state.timer);
		state.timer = setTimeout(() => this.preview(frm), this.DELAY);
	},

	scheduleSummary(frm) {
		const state = this.state(frm);
		clearTimeout(state.summaryTimer);
		state.summaryTimer = setTimeout(() => this.loadSummary(frm), this.DELAY);
	},

	// Only target_amount is written; target_rate is never touched.
	async preview(frm) {
		const state = this.state(frm);
		const doc = frm.doc;
		if (!this.isBalance(frm) || doc.docstatus !== 0 || !doc.company || !doc.target_currency) {
			return;
		}
		const request = ++state.previewRequest;
		const amounts = await frappe.xcall(spConversionLegs.method("receipt_conversion_api.preview_target_amounts"), {
			company: doc.company,
			target_currency: doc.target_currency,
			legs: [{ name: "total", conversion_amount: doc.conversion_amount, target_rate: doc.target_rate }],
		});
		if (request !== state.previewRequest || state.doc !== frm.doc) {
			return;
		}
		const value = spConversionLegs.previewValue(amounts?.total);
		if ((frm.doc.target_amount ?? null) !== value) {
			frm.doc.target_amount = value;
			frm.refresh_field("target_amount");
		}
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = spBalanceForm;
}
