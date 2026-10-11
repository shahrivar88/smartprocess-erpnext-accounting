// Ledger page → display groups. One group per GL line, always in chronological
// order (posting date, creation, name) so the running balance is never misleading;
// a split invoice line keeps its item/adjustment rows, each repeating the date and
// the document. Search and debit/credit filters run on the server.
const pae_ledger_rows = {
	groups(lines, offset, split) {
		return (lines || []).map((line, index) => pae_ledger_rows.group(line, offset + index + 1, split));
	},

	group(line, position, split) {
		const doc = {
			label: line.voucher_label,
			number: line.document_number,
			doctype: line.document ? line.document.doctype : null,
			name: line.document ? line.document.name : null,
		};
		const voucher = {
			number: line.voucher_no,
			doctype: line.voucher ? line.voucher.doctype : null,
			name: line.voucher ? line.voucher.name : null,
			detail: line.detail_ref || "",
		};
		const components = split && line.components && line.components.length ? line.components : null;
		const entries = components || [pae_ledger_rows.plain_entry(line)];
		const badges = pae_ledger_rows.badges(line);
		const rows = entries.map((entry, index) => ({
			gl_entry: line.gl_entry,
			number: entries.length > 1 ? `${position}.${index + 1}` : String(position),
			first: index === 0,
			last: index === entries.length - 1,
			kind: entry.kind || "line",
			date: line.posting_date,
			doc,
			voucher,
			account: line.account,
			description: entry.description || "",
			title: entry.title || "",
			qty: entry.qty,
			rate: entry.rate,
			rate_base: entry.rate_base,
			debit: flt(entry.debit),
			credit: flt(entry.credit),
			debit_base: flt(entry.debit_base),
			credit_base: flt(entry.credit_base),
			balance: entry.balance,
			nature: entry.nature,
			balance_base: entry.balance_base,
			badges: index === 0 ? badges : [],
		}));
		return { gl_entry: line.gl_entry, position, line, doc, voucher, rows };
	},

	plain_entry(line) {
		return {
			kind: "line",
			description: line.remarks || "",
			title: "",
			qty: null,
			rate: null,
			rate_base: null,
			debit: line.debit,
			credit: line.credit,
			debit_base: line.debit_base,
			credit_base: line.credit_base,
			balance: line.balance,
			nature: line.nature,
			balance_base: line.balance_base,
		};
	},

	// A row posted in another currency is shown and labelled, never dropped.
	badges(line) {
		const badges = [];
		if (line.posted_in_other_currency) {
			badges.push({ type: "posted", currency: line.posted_currency });
		}
		if (line.transaction_currency) {
			badges.push({ type: "transaction", currency: line.transaction_currency, amount: Math.abs(flt(line.transaction_amount)) });
		}
		return badges;
	},

	is_filtered(filters) {
		return Boolean(filters && (String(filters.search || "").trim() || filters.side));
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = { pae_ledger_rows };
}
