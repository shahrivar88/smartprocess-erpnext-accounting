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

		return { compactFormattedNumber };
	},
);
