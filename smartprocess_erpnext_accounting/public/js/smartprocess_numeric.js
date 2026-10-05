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

		// Live thousands-separator input mask. Presentation only: the input text is
		// re-grouped while typing while the owning control's parse() receives the
		// cleaned text, so the model/DocField value stays a raw number. Attached
		// per-control (instance scoped) — never on the Frappe control prototypes.
		const NUMERIC_INPUT_CHARS = /[0-9.eE+\-*/()]/;

		function normalizedConfig(config) {
			const merged = config || {};
			return {
				enabled: Boolean(merged.enabled),
				separator:
					typeof merged.separator === "string" && merged.separator !== ""
						? merged.separator
						: ",",
				decimal_str: merged.decimal_str || ".",
				group_str: typeof merged.group_str === "string" ? merged.group_str : ",",
			};
		}

		// Strips every non-numeric display character (the configured separator, the
		// site group separator, stray pasted group chars) and normalizes the site
		// decimal character to ".". Expression characters (+ - * / ( ) e E) survive
		// so the standard math-expression input keeps working.
		function cleanNumericText(value, config) {
			if (typeof value !== "string") {
				return value;
			}
			const { decimal_str, group_str } = normalizedConfig(config);
			let text = value;
			if (group_str) {
				text = text.split(group_str).join("");
			}
			if (decimal_str !== ".") {
				text = text.split(decimal_str).join(".");
			}
			return text.replace(/[^0-9.eE+\-*/()]/g, "");
		}

		// Groups the integer part of a plain number with config.separator. Returns the
		// input unchanged unless the whole text is a simple number (sign, digits, at
		// most one decimal point), so expressions and partial states stay untouched.
		// Output is canonical (always "." decimal); use toDisplayNumericText before
		// writing it back to the DOM.
		function formatLiveNumberText(text, config) {
			const { separator } = normalizedConfig(config);
			const cleaned = cleanNumericText(text, config);
			if (!/^[+\-]?\d*\.?\d*$/.test(cleaned) || !/\d/.test(cleaned)) {
				return text;
			}
			const sign = /^[+\-]/.test(cleaned) ? cleaned[0] : "";
			const unsigned = sign ? cleaned.slice(1) : cleaned;
			const dotIndex = unsigned.indexOf(".");
			const integerPart = dotIndex < 0 ? unsigned : unsigned.slice(0, dotIndex);
			const fractionPart = dotIndex < 0 ? null : unsigned.slice(dotIndex + 1);
			return (
				sign +
				integerPart.replace(/\B(?=(\d{3})+(?!\d))/g, separator) +
				(fractionPart === null ? "" : "." + fractionPart)
			);
		}

		function toDisplayNumericText(canonicalText, config) {
			const { decimal_str } = normalizedConfig(config);
			// Translate only the trailing decimal dot; the separator itself may be a dot.
			return decimal_str === "." ? canonicalText : canonicalText.replace(/\.(?=[^.]*$)/, decimal_str);
		}

		// Caret mapping between the pre-format text and the canonical output: counts
		// meaningful characters before the caret and lands on the same count in the
		// new text, so the cursor never jumps to the end while typing mid-number.
		function mapCaret(oldPrefixText, newText) {
			let meaningful = 0;
			for (const char of oldPrefixText) {
				if (NUMERIC_INPUT_CHARS.test(char)) {
					meaningful += 1;
				}
			}
			if (meaningful === 0) {
				return 0;
			}
			let seen = 0;
			for (let i = 0; i < newText.length; i += 1) {
				if (NUMERIC_INPUT_CHARS.test(newText[i])) {
					seen += 1;
					if (seen === meaningful) {
						return i + 1;
					}
				}
			}
			return newText.length;
		}

		// getConfig() must return the live settings object ({enabled, separator,
		// decimal_str, group_str}); it is re-read on every event so a settings change
		// after a form reload takes effect without re-attaching. attach() may run
		// before the settings arrive (enabled is still 0): the parse wrapper and the
		// input listener both re-check enabled live, so nothing changes the standard
		// behavior until the feature is actually on.
		function attach(control, getConfig) {
			if (!control || typeof control.parse !== "function") {
				return;
			}
			if (!control.__sp_live_separator_parse) {
				control.__sp_live_separator_parse = true;
				const originalParse = control.parse;
				control.parse = function (value) {
					const config = normalizedConfig(getConfig());
					return originalParse.call(
						this,
						config.enabled ? cleanNumericText(value, config) : value,
					);
				};
			}
			const $input = control.$input;
			const element = $input && typeof $input.get === "function" ? $input.get(0) : $input;
			if (
				!element ||
				typeof element.addEventListener !== "function" ||
				element.__sp_live_separator_input
			) {
				return;
			}
			element.__sp_live_separator_input = true;
			element.addEventListener("input", () => {
				const config = getConfig();
				if (!config || !normalizedConfig(config).enabled) {
					return;
				}
				const canonical = formatLiveNumberText(element.value, config);
				if (canonical === element.value) {
					return;
				}
				const caretStart =
					element.selectionStart == null ? element.value.length : element.selectionStart;
				const caret = mapCaret(element.value.slice(0, caretStart), canonical);
				element.value = toDisplayNumericText(canonical, config);
				const clamped = Math.min(caret, element.value.length);
				element.setSelectionRange(clamped, clamped);
			});
		}

		return {
			compactFormattedNumber,
			liveNumberSeparator: {
				cleanNumericText,
				formatLiveNumberText,
				toDisplayNumericText,
				mapCaret,
				attach,
			},
		};
	},
);
