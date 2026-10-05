// Receipt Conversion client helpers. Pure functions: amounts are calculated on the server only.
const spConversionLegs = {
	API: "smartprocess_erpnext_accounting.smartprocess_accounting",
	LEG: "SmartProcess Receipt Conversion Leg",
	TABLE: "legs",
	PARTY_TYPES: ["Customer", "Supplier", "Employee", "SmartProcess Financial Intermediary"],
	PARTY_ACCOUNT_TYPES: {
		Customer: "Receivable",
		"SmartProcess Financial Intermediary": "Receivable",
		Supplier: "Payable",
		Employee: "Payable",
	},
	SIDE_LABELS: { Receiver: "دریافت‌کننده", Payer: "پرداخت‌کننده" },
	SOURCE_FIELDS: [
		"source_pair",
		"source_side",
		"source_posting",
		"source_account",
		"source_party_type",
		"source_party",
		"company_currency",
		"original_amount",
		"already_converted",
		"remaining_amount",
	],
	SUGGESTION_FIELDS: ["target_party_type", "target_party", "target_account"],

	method(path) {
		return `${this.API}.${path}`;
	},

	key(leg) {
		return `${leg.source_pair}|${leg.source_side}`;
	},

	// Fresh server legs for the selected currency. Only the Conversion Amount of
	// a still-offered side carries over; targets, rates and amounts start again.
	mergeLegs(existing, fresh, targetCurrency) {
		const amounts = new Map((existing || []).map((leg) => [this.key(leg), leg.conversion_amount]));
		return (fresh || []).map((leg) => {
			const row = { target_currency: targetCurrency || "", conversion_amount: amounts.get(this.key(leg)) || 0 };
			for (const fieldname of [...this.SOURCE_FIELDS, ...this.SUGGESTION_FIELDS]) {
				if (leg[fieldname] !== null && leg[fieldname] !== undefined) {
					row[fieldname] = leg[fieldname];
				}
			}
			return row;
		});
	},

	// Rates and user-edited targets count as input; prefilled suggestions do not.
	hasTargetInput(legs, touched) {
		return (touched?.size || 0) > 0 || (legs || []).some((leg) => Number(leg.target_rate) > 0);
	},

	clearedTargets() {
		return { target_party_type: "", target_party: "", target_account: "", target_rate: null, target_amount: null };
	},

	currencyFilters(companyCurrency) {
		return { enabled: 1, name: ["!=", companyCurrency || ""] };
	},

	// A chosen Party narrows the Account to its native type; the server still validates.
	accountFilters(company, currency, partyType, party) {
		const filters = { company: company || "", disabled: 0, is_group: 0, account_currency: currency || "" };
		const accountType = party ? this.PARTY_ACCOUNT_TYPES[partyType] : null;
		if (accountType) {
			filters.account_type = accountType;
		}
		return filters;
	},

	isPartyAccountType(accountType) {
		return ["Receivable", "Payable"].includes(accountType);
	},

	previewPayload(legs) {
		return (legs || []).map((leg) => ({
			name: leg.name,
			conversion_amount: leg.conversion_amount,
			target_rate: leg.target_rate,
		}));
	},

	previewValue(amount) {
		return amount === null || amount === undefined ? null : Number(amount);
	},

	hasPositiveAmount(legs) {
		return (legs || []).some((leg) => Number(leg.conversion_amount) > 0);
	},

	sideLabel(side) {
		return this.SIDE_LABELS[side] || side || "";
	},

	partyAccountLabel(account, partyType, party, titleOf) {
		if (!party) {
			return account || "";
		}
		const title = titleOf(partyType, party) || party;
		return account ? `${title} · ${account}` : title;
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = spConversionLegs;
}
