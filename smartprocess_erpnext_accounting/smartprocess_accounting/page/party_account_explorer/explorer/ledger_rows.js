// Ledger page → display groups. One group per GL line; a split invoice line keeps
// its item/adjustment rows, each repeating the date and the document. Sorting and
// filtering move or hide whole groups of the loaded page only; balances are never
// recomputed here.
const PAE_SORTS = {
	number: (group) => group.position,
	date: (group) => String(group.line.posting_date || ""),
	document: (group) => `${group.doc.label || ""} ${group.doc.number || ""}`,
	debit: (group) => flt(group.line.debit),
	credit: (group) => flt(group.line.credit),
};

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
			description: entry.description || "",
			title: entry.title || "",
			item_code: entry.item_code || "",
			qty: entry.qty,
			rate: entry.rate,
			debit: flt(entry.debit),
			credit: flt(entry.credit),
			posting_rate: line.rate,
			balance: entry.balance,
			nature: entry.nature,
			balance_base: entry.balance_base,
			detail_ref: line.detail_ref || "",
			badges: index === 0 ? badges : [],
		}));
		return { gl_entry: line.gl_entry, position, line, doc, rows };
	},

	plain_entry(line) {
		return {
			kind: "line",
			description: line.remarks || "",
			title: "",
			qty: null,
			rate: null,
			debit: line.debit,
			credit: line.credit,
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

	search_text(group) {
		const parts = [group.doc.label, group.doc.number, group.line.remarks, group.line.detail_ref];
		group.rows.forEach((row) => parts.push(row.title, row.description, row.item_code));
		return parts.filter(Boolean).join(" ").toLowerCase();
	},

	view(groups, state) {
		const query = String((state && state.query) || "").trim().toLowerCase();
		const side = state && state.side;
		let out = groups.filter((group) => {
			if (side === "debit" && !flt(group.line.debit)) {
				return false;
			}
			if (side === "credit" && !flt(group.line.credit)) {
				return false;
			}
			return !query || pae_ledger_rows.search_text(group).includes(query);
		});
		const key = PAE_SORTS[state && state.sort_key];
		if (key) {
			const direction = state.sort_dir === "desc" ? -1 : 1;
			out = out.slice().sort((a, b) => direction * (pae_ledger_rows.compare(key(a), key(b)) || a.position - b.position));
		}
		return out;
	},

	compare(a, b) {
		if (typeof a === "number" && typeof b === "number") {
			return a - b;
		}
		return String(a).localeCompare(String(b), "fa");
	},

	is_filtered(state) {
		return Boolean(state && (String(state.query || "").trim() || state.side || PAE_SORTS[state.sort_key]));
	},

	next_sort(state, key) {
		if (state.sort_key !== key) {
			return { sort_key: key, sort_dir: "asc" };
		}
		if (state.sort_dir === "asc") {
			return { sort_key: key, sort_dir: "desc" };
		}
		return { sort_key: null, sort_dir: null };
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = { pae_ledger_rows, PAE_SORTS };
}
