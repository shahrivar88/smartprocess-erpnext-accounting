(function (root, factory) {
	const numeric = factory();
	if (typeof module === "object" && module.exports && !root?.document) {
		module.exports = numeric;
	}
	if (root) {
		root.smartprocessAccounting = root.smartprocessAccounting || {};
		root.smartprocessAccounting.numeric = numeric;
		installTrailingZeroDisplay(root, numeric);
		hydrateDisplayMaps(root);
	}

	// frappe.boot is assigned before app_include_js runs. With the setting off the
	// formatter registry is left untouched, so output is exactly native Frappe.
	function installTrailingZeroDisplay(win, api) {
		const frappe = win.frappe;
		if (
			!frappe?.boot?.smartprocess_accounting?.hide_insignificant_trailing_zeros ||
			!frappe.form?.formatters ||
			typeof win.get_number_format !== "function" ||
			typeof win.get_number_format_info !== "function"
		) {
			return;
		}
		api.wrapNumericFormatters(
			frappe.form.formatters,
			(fieldtype, docfield, doc) => {
				const currency =
					fieldtype === "Currency" ? frappe.meta.get_field_currency(docfield, doc) : null;
				return win.get_number_format_info(win.get_number_format(currency)).decimal_str;
			},
			(doctype, parenttype) => api.trailingZerosEnabledFor(doctype, parenttype),
		);
	}

	function hydrateDisplayMaps(win) {
		const frappe = win.frappe;
		const flags = frappe?.boot?.smartprocess_accounting;
		if (!flags || !frappe.db?.get_value || flags.hide_trailing_zeros_doctypes) {
			return;
		}
		const slugs = [
			["sales_invoice", "Sales Invoice"],
			["purchase_invoice", "Purchase Invoice"],
			["quotation", "Quotation"],
			["sales_order", "Sales Order"],
			["purchase_order", "Purchase Order"],
		];
		const follow = [
			"Payment Entry",
			"SmartProcess Accounting Document",
			"SmartProcess Accounting Posting",
			"SmartProcess Receipt Conversion",
			"SmartProcess Currency Conversion",
		];
		const fields = slugs.flatMap(([slug]) => [`hide_trailing_zeros_${slug}`, `live_separator_${slug}`]);
		frappe.db.get_value("SmartProcess Accounting Settings", "SmartProcess Accounting Settings", fields, (row) => {
			if (!row) {
				return;
			}
			const zeros = {};
			const separators = {};
			const masterZeros = Number(flags.hide_insignificant_trailing_zeros);
			const masterSep = Number(flags.live_number_separator?.enabled);
			for (const [slug, doctype] of slugs) {
				zeros[doctype] = masterZeros && Number(row[`hide_trailing_zeros_${slug}`]) ? 1 : 0;
				separators[doctype] = masterSep && Number(row[`live_separator_${slug}`]) ? 1 : 0;
			}
			for (const doctype of follow) {
				zeros[doctype] = masterZeros ? 1 : 0;
				separators[doctype] = masterSep ? 1 : 0;
			}
			flags.hide_trailing_zeros_doctypes = zeros;
			flags.live_separator_doctypes = separators;
		});
	}

})(
	typeof window !== "undefined"
		? window
		: typeof globalThis === "undefined"
			? this
			: globalThis,
	() => {
		function escapeRegExp(text) {
			return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
		}

		// String-only: trims the trailing zeros of the last "<digit><decimal><digits>"
		// run, so currency symbols, HTML wrappers, signs and group separators stay
		// as formatted and the value is never re-parsed as a JS number.
		function compactFormattedNumber(formattedValue, decimalSeparator = ".") {
			if (formattedValue === null || formattedValue === undefined) {
				return "";
			}

			const formatted = String(formattedValue);
			if (!decimalSeparator) {
				return formatted;
			}

			const pattern = new RegExp(`\\d(${escapeRegExp(decimalSeparator)})(\\d+)(?!\\d)`, "g");
			let last = null;
			for (const match of formatted.matchAll(pattern)) {
				last = match;
			}
			if (!last) {
				return formatted;
			}

			const decimalIndex = last.index + 1;
			const meaningfulFraction = last[2].replace(/0+$/, "");
			const fraction = meaningfulFraction ? decimalSeparator + meaningfulFraction : "";
			return (
				formatted.slice(0, decimalIndex) +
				fraction +
				formatted.slice(decimalIndex + decimalSeparator.length + last[2].length)
			);
		}

		// Display-only wrap of the standard numeric entries of frappe.form.formatters
		// (the registry frappe.format() resolves on every call). Each wrapper returns
		// the original formatter's string with only its trailing fractional zeros
		// removed; inputs, raw values and precision are never touched.
		const TRAILING_ZERO_FIELDTYPES = ["Currency", "Float", "Percent"];

		function delegatesToCurrency(fieldtype, docfield) {
			// Float with options is rendered by the (already wrapped) Currency formatter.
			return fieldtype === "Float" && Boolean(docfield?.options && String(docfield.options).trim());
		}

		function resolveDisplayDoctype(docfield, doc) {
			return {
				doctype: (doc && doc.doctype) || (docfield && (docfield.parent || docfield.doctype)) || "",
				parenttype: (doc && doc.parenttype) || "",
			};
		}

		function trailingZerosEnabledFor(doctype, parenttype) {
			const boot = globalThis.frappe?.boot?.smartprocess_accounting || {};
			if (!Number(boot.hide_insignificant_trailing_zeros)) {
				return false;
			}
			const map = boot.hide_trailing_zeros_doctypes;
			if (!map) {
				return true;
			}
			if (doctype && Number(map[doctype])) {
				return true;
			}
			if (parenttype && Number(map[parenttype])) {
				return true;
			}
			return false;
		}

		function liveSeparatorConfigFor(doctype, parenttype) {
			const boot = globalThis.frappe?.boot?.smartprocess_accounting || {};
			const base = Object.assign({}, boot.live_number_separator || {});
			const map = boot.live_separator_doctypes;
			if (!map) {
				return base;
			}
			base.enabled = Boolean(
				Number(base.enabled) && ((doctype && Number(map[doctype])) || (parenttype && Number(map[parenttype]))),
			);
			return base;
		}

		function wrapNumericFormatters(formatters, decimalFor, isEnabled) {
			if (!formatters || formatters.__spTrailingZeros) {
				return false;
			}
			for (const fieldtype of TRAILING_ZERO_FIELDTYPES) {
				const original = formatters[fieldtype];
				if (typeof original !== "function") {
					continue;
				}
				formatters[fieldtype] = function (...args) {
					const formatted = original.apply(this, args);
					const [, docfield, , doc] = args;
					// Reports pass always_show_decimals; the global setting overrides it.
					if (typeof formatted !== "string" || delegatesToCurrency(fieldtype, docfield)) {
						return formatted;
					}
					if (typeof isEnabled === "function") {
						const target = resolveDisplayDoctype(docfield, doc);
						if (!isEnabled(target.doctype, target.parenttype)) {
							return formatted;
						}
					}
					return compactFormattedNumber(formatted, decimalFor(fieldtype, docfield, doc));
				};
			}
			Object.defineProperty(formatters, "__spTrailingZeros", { value: true });
			return true;
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
			wrapNumericFormatters,
			trailingZerosEnabledFor,
			liveSeparatorConfigFor,
			resolveDisplayDoctype,
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
