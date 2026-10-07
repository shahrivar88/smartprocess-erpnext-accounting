const assert = require("node:assert/strict");

const escape_html = (value) =>
	String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const slug = (doctype) => doctype.toLowerCase().replace(/ /g, "-");

globalThis.__ = (text, args) => String(text).replace(/\{(\d+)\}/g, (_match, index) => (args || [])[index]);
globalThis.flt = (value) => Number(value) || 0;
globalThis.cint = (value) => parseInt(value, 10) || 0;
globalThis.get_number_format = () => "#,###";
globalThis.get_number_format_info = () => ({ precision: 0 });
globalThis.frappe = {
	defaults: { get_default: () => null },
	format: (value, df) => (df.fieldtype === "Date" ? `D:${value}` : String(value)),
	utils: {
		escape_html,
		get_form_link: (doctype, name) => `/desk/${slug(doctype)}/${encodeURIComponent(name)}`,
	},
};

const { pae_format } = require("../page/party_account_explorer/explorer/format.js");
globalThis.pae_format = pae_format;
const { pae_ledger_rows } = require("../page/party_account_explorer/explorer/ledger_rows.js");
globalThis.pae_ledger_rows = pae_ledger_rows;
const { PaeColumnPrefs, PAE_SETTINGS_KEY } = require("../page/party_account_explorer/explorer/column_prefs.js");
const { pae_ledger_view } = require("../page/party_account_explorer/explorer/ledger_view.js");
const { pae_detail_view } = require("../page/party_account_explorer/explorer/detail_view.js");

const CONTEXT = { currency: "IRR", company_currency: "IRR", is_foreign: false };

function invoice_line(extra) {
	return {
		gl_entry: "GL-1",
		posting_date: "2026-05-01",
		voucher_label: "فاکتور فروش",
		document_number: "ACC-SINV-2026-00012",
		document: { doctype: "Sales Invoice", name: "ACC-SINV-2026-00012" },
		remarks: "No Remarks",
		debit: 215000000,
		credit: 0,
		balance: -485000000,
		nature: "بستانکار",
		balance_base: -485000000,
		detail_ref: null,
		components: [
			{ kind: "item", title: "DS-2CD2347G2-L (2.8mm)", item_code: "CAM-1", description: "", qty: 10, rate: 21000000, debit: 210000000, credit: 0, balance: -490000000, nature: "بستانکار" },
			{ kind: "tax", title: "مالیات و عوارض", description: "", qty: null, rate: null, debit: 5000000, credit: 0, balance: -485000000, nature: "بستانکار" },
		],
		...extra,
	};
}

// Combined document cell: label, then the number as a real link to the business form.
{
	const html = pae_format.document({ label: "رسید", number: "SP-REC-2026-00019", doctype: "SmartProcess Accounting Document", name: "SP-REC-2026-00019" });
	assert.match(html, /<span class="sp-doc-type">رسید<\/span> - <a class="sp-doc-link" href="\/desk\/smartprocess-accounting-document\/SP-REC-2026-00019"/);
	assert.match(html, />SP-REC-2026-00019<\/a>/);
	const plain = pae_format.document({ label: "سند حسابداری", number: "JV-9", doctype: null, name: null });
	assert.equal(plain.includes("<a "), false, "an unreadable document stays plain text");
	assert.match(plain, /سند حسابداری<\/span> - JV-9/);
}

// Split invoice rows each repeat the date and document; none is a blank header.
{
	const [group] = pae_ledger_rows.groups([invoice_line()], 0, true);
	assert.equal(group.rows.length, 2, "one row per component, no extra header row");
	assert.deepEqual(group.rows.map((row) => row.number), ["1.1", "1.2"]);
	group.rows.forEach((row) => {
		assert.equal(row.doc.number, "ACC-SINV-2026-00012");
		assert.equal(row.doc.label, "فاکتور فروش");
		assert.equal(row.date, "2026-05-01");
		assert.ok(row.debit || row.credit, "every row carries an amount");
	});
	const total = group.rows.reduce((sum, row) => sum + row.debit, 0);
	assert.equal(total, 215000000, "split rows add up to the GL line");
	assert.equal(group.rows[0].title, "DS-2CD2347G2-L (2.8mm)", "the item name only");
	assert.equal(group.rows[0].item_code, "CAM-1", "the item code stays in the row data");
	assert.equal(group.rows[0].qty * group.rows[0].rate, group.rows[0].debit);
	assert.deepEqual([group.rows[0].first, group.rows[1].last], [true, true]);

	const html = pae_ledger_view.group_rows(group, pae_ledger_view.columns(CONTEXT), CONTEXT, false);
	assert.equal((html.match(/class="sp-doc-link"/g) || []).length, 2, "the document link repeats on every row");
	assert.equal((html.match(/sp-detail-btn/g) || []).length, 1, "one details button per GL line");
	assert.equal(html.includes("CAM-1"), false, "no item code in the main table");
	assert.equal(html.includes("uom"), false);
}

// Without item split a line is one row with its own amount.
{
	const [group] = pae_ledger_rows.groups([invoice_line()], 100, false);
	assert.equal(group.rows.length, 1);
	assert.equal(group.rows[0].number, "101", "numbering continues across server pages");
	assert.equal(group.rows[0].debit, 215000000);
	assert.equal(group.rows[0].description, "No Remarks");
}

// A row in another currency is labelled, never dropped.
{
	const line = invoice_line({ components: [], posted_in_other_currency: true, posted_currency: "USD", transaction_currency: "EUR", transaction_amount: -50 });
	const [group] = pae_ledger_rows.groups([line], 0, true);
	assert.deepEqual(group.rows[0].badges, [
		{ type: "posted", currency: "USD" },
		{ type: "transaction", currency: "EUR", amount: 50 },
	]);
	const html = pae_ledger_view.cell("description", group.rows[0], CONTEXT, false);
	assert.match(html, /ارز ثبت: USD/);
	assert.match(html, /ارز سند: EUR/);
	assert.match(pae_ledger_view.currency_cell("IRR", 3), /3 ردیف با ارز دیگر/);
	assert.equal(pae_ledger_view.currency_cell("IRR", 0), "IRR");
}

// Filtering and sorting keep groups whole and never touch amounts.
{
	const lines = [
		invoice_line(),
		{ ...invoice_line({ gl_entry: "GL-2", document_number: "SP-REC-2026-00019", voucher_label: "رسید", components: [], debit: 0, credit: 700000000 }) },
	];
	const groups = pae_ledger_rows.groups(lines, 0, true);
	const by_item = pae_ledger_rows.view(groups, { query: "ds-2cd" });
	assert.equal(by_item.length, 1);
	assert.equal(by_item[0].rows.length, 2, "a matching item keeps its whole invoice");
	assert.deepEqual(pae_ledger_rows.view(groups, { side: "credit" }).map((group) => group.gl_entry), ["GL-2"]);
	assert.deepEqual(pae_ledger_rows.view(groups, { sort_key: "credit", sort_dir: "desc" }).map((group) => group.gl_entry), ["GL-2", "GL-1"]);
	assert.deepEqual(pae_ledger_rows.view(groups, {}).map((group) => group.gl_entry), ["GL-1", "GL-2"]);
	assert.equal(groups[0].rows[0].balance, -490000000, "the view never recomputes balances");
	assert.deepEqual(pae_ledger_rows.next_sort({}, "debit"), { sort_key: "debit", sort_dir: "asc" });
	assert.deepEqual(pae_ledger_rows.next_sort({ sort_key: "debit", sort_dir: "asc" }, "debit"), { sort_key: "debit", sort_dir: "desc" });
	assert.deepEqual(pae_ledger_rows.next_sort({ sort_key: "debit", sort_dir: "desc" }, "debit"), { sort_key: null, sort_dir: null });
	assert.equal(pae_ledger_rows.is_filtered({ query: " " }), false);
	assert.equal(pae_ledger_rows.is_filtered({ side: "debit" }), true);
	assert.match(pae_ledger_view.status({ side: "debit" }, 1, 2), /1 از 2/);
}

// Opening and totals rows put the label in the document column.
{
	const columns = pae_ledger_view.columns(CONTEXT);
	const html = pae_ledger_view.balance_row("sp-total-row", columns, CONTEXT, { label: "جمع گردش کل دوره", debit: 5, credit: 0, balance: 15, nature: "بدهکار" });
	const cells = html.match(/<td[^>]*>.*?<\/td>/g);
	const at = (key) => cells[columns.findIndex((column) => column.key === key)];
	assert.equal(cells.length, columns.length);
	assert.match(at("document"), /جمع گردش کل دوره/);
	assert.match(at("debit"), />5</);
	assert.match(at("credit"), />0</);
	assert.match(at("balance"), />15</);
}

// The foreign view keeps the posting rate and the company-currency balance.
{
	const foreign = { currency: "USD", company_currency: "IRR", is_foreign: true };
	const keys = pae_ledger_view.columns(foreign).map((column) => column.key);
	assert.ok(keys.includes("posting_rate"));
	assert.equal(keys[keys.length - 2], "balance_base");
	assert.equal(pae_ledger_view.columns(CONTEXT).some((column) => column.key === "balance_base"), false);
}

// Column widths: cleaned on load, clamped, saved per table without dropping the others.
(async () => {
	const saved = [];
	const store = {
		get: () => Promise.resolve({ column_widths: { ledger: { debit: 5000, bad: "x" }, overview: { party: 200 } } }),
		save: (key, field, value) => {
			saved.push([key, field, value]);
			return Promise.resolve();
		},
	};
	const prefs = new PaeColumnPrefs(store);
	await prefs.load();
	assert.equal(store[PAE_SETTINGS_KEY].column_widths.overview.party, 200, "the settings cache is filled before any save");
	assert.equal(prefs.width("ledger", "debit", 140), 900, "stored widths are clamped");
	assert.equal(prefs.width("ledger", "bad", 140), 140, "invalid widths fall back to the default");
	assert.equal(prefs.width("overview", "party", 240), 200);
	prefs.remember("ledger", "credit", 123.4);
	clearTimeout(prefs.timer);
	await prefs.persist("ledger");
	assert.deepEqual(saved, [[PAE_SETTINGS_KEY, "column_widths", { ledger: { debit: 900, credit: 123 } }]]);
	prefs.remember("ledger", "credit", null);
	clearTimeout(prefs.timer);
	assert.equal(prefs.width("ledger", "credit", 140), 140, "a reset column returns to its default");
	assert.match(pae_ledger_view.colgroup(pae_ledger_view.columns(CONTEXT), prefs, "ledger"), /data-col="debit" style="width:900px"/);

	const broken = new PaeColumnPrefs({ get: () => Promise.reject(new Error("offline")), save: () => Promise.resolve() });
	await broken.load();
	assert.equal(broken.width("ledger", "debit", 140), 140, "a failed load keeps the defaults");
})();

// Inline details: read-only summary plus a link to the full document.
{
	const html = pae_detail_view.html({
		title: "فاکتور فروش",
		document: { doctype: "Sales Invoice", name: "ACC-SINV-2026-00012" },
		summary: [{ label: "مبلغ کل", kind: "amount", value: 210000000, currency: "IRR" }],
		sections: [{ title: "اقلام", columns: [{ key: "item_code", label: "کد کالا", kind: "text" }], rows: [{ item_code: "CAM-1" }] }],
		related: [],
		technical: [],
	});
	assert.match(html, /href="\/desk\/sales-invoice\/ACC-SINV-2026-00012"[^>]*>باز کردن سند کامل/);
	assert.match(html, /CAM-1/, "the item code appears in the details");
	assert.equal(html.includes("<input"), false, "details are read-only");
	assert.match(pae_ledger_view.detail_row("GL-1", pae_ledger_view.columns(CONTEXT), html), /colspan="\d+"/);
}

console.log("party account explorer UI tests passed");
