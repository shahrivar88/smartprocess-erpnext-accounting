function currency_precision(currency) {
	// Same rule frappe applies to Currency fields: the site's currency precision,
	// otherwise the currency's own number format.
	const configured = cint(frappe.defaults.get_default("currency_precision"));
	if (configured) {
		return configured;
	}
	return get_number_format_info(get_number_format(currency)).precision;
}

const pae_format = {
	amount(value, currency, keep_zero) {
		if (value === null || value === undefined || value === "") {
			return "";
		}
		if (!keep_zero && !flt(value)) {
			return "";
		}
		const text = frappe.format(flt(value), { fieldtype: "Float", precision: currency_precision(currency) }, { inline: true });
		return `<span class="sp-num">${text}</span>`;
	},
	rate(value) {
		if (!flt(value)) {
			return "";
		}
		return `<span class="sp-num">${frappe.format(flt(value), { fieldtype: "Float", precision: 9 }, { inline: true })}</span>`;
	},
	number(value) {
		if (value === null || value === undefined || value === "") {
			return "";
		}
		return `<span class="sp-num">${frappe.format(flt(value), { fieldtype: "Float" }, { inline: true })}</span>`;
	},
	date(value) {
		return value ? frappe.format(value, { fieldtype: "Date" }) : "";
	},
	text(value) {
		return frappe.utils.escape_html(value === null || value === undefined ? "" : String(value));
	},
	link(doctype, name, label) {
		const text = pae_format.text(label || name);
		if (!doctype || !name) {
			return text;
		}
		const href = frappe.utils.get_form_link(doctype, name);
		return `<a class="sp-doc-link" href="${href}" data-doctype="${pae_format.text(doctype)}" data-name="${pae_format.text(name)}">${text}</a>`;
	},
	// «نوع سند - شماره سند»; the number opens the full business document.
	document(doc) {
		const number = pae_format.link(doc.doctype, doc.name, doc.number);
		return `<span class="sp-doc-cell"><span class="sp-doc-type">${pae_format.text(doc.label)}</span> - ${number}</span>`;
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = { pae_format, currency_precision };
}
