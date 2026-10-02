(function (root, factory) {
	const numeric = factory();
	if (typeof module === "object" && module.exports) {
		module.exports = numeric;
	}
	if (root) {
		root.smartprocessAccounting = root.smartprocessAccounting || {};
		root.smartprocessAccounting.numeric = numeric;
	}
})(
	typeof window !== "undefined"
		? window
		: typeof globalThis === "undefined"
			? this
			: globalThis,
	() => {
		function compactFormattedNumber(formattedValue, decimalSeparator = ".") {
			if (formattedValue === null || formattedValue === undefined) {
				return "";
			}

			const formatted = String(formattedValue);
			if (!decimalSeparator) {
				return formatted;
			}

			const decimalIndex = formatted.lastIndexOf(decimalSeparator);
			if (decimalIndex < 0) {
				return formatted;
			}

			const fractionAndSuffix = formatted.slice(decimalIndex + decimalSeparator.length);
			const match = fractionAndSuffix.match(/^(\d+)(.*)$/s);
			if (!match) {
				return formatted;
			}

			const meaningfulFraction = match[1].replace(/0+$/, "");
			const fraction = meaningfulFraction ? decimalSeparator + meaningfulFraction : "";
			return formatted.slice(0, decimalIndex) + fraction + match[2];
		}

		function summarizeReceiptRows(rows, companyCurrency) {
			const totals = new Map();
			let companyTotal = 0;
			for (const row of rows || []) {
				const currency = row.receipt_currency;
				const amount = Number(row.credit_amount || 0);
				if (!currency || !Number.isFinite(amount) || amount <= 0) {
					continue;
				}
				const storedBase = Number(row.credit_company_amount || 0);
				const baseAmount = currency === companyCurrency
					? amount
					: Number.isFinite(storedBase) && storedBase > 0 ? storedBase : 0;
				const current = totals.get(currency) || { currency, amount: 0, baseAmount: 0 };
				current.amount += amount;
				current.baseAmount += baseAmount;
				totals.set(currency, current);
				companyTotal += baseAmount;
			}
			const currencies = [...totals.values()].map((row) => ({
				...row,
				weightedRate: row.currency === companyCurrency || row.amount === 0
					? null
					: row.baseAmount / row.amount,
			}));
			return { currencies, companyTotal };
		}

		return { compactFormattedNumber, summarizeReceiptRows };
	},
);
