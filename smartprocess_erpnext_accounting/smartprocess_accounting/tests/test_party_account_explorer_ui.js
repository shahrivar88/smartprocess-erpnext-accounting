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
		voucher_no: "ACC-SINV-2026-00012",
		voucher: { doctype: "Sales Invoice", name: "ACC-SINV-2026-00012" },
		account: "Debtors - SP",
		remarks: "No Remarks",
		debit: 215000000,
		credit: 0,
		debit_base: 215000000,
		credit_base: 0,
		balance: -485000000,
		nature: "بستانکار",
		balance_base: -485000000,
		detail_ref: null,
		components: [
			{ kind: "item", title: "DS-2CD2347G2-L (2.8mm)", item_code: "CAM-1", description: "", qty: 10, rate: 21000000, rate_base: 21000000, debit: 210000000, credit: 0, debit_base: 210000000, credit_base: 0, balance: -490000000, nature: "بستانکار", balance_base: -490000000 },
			{ kind: "tax", title: "مالیات و عوارض", description: "", qty: null, rate: null, rate_base: null, debit: 5000000, credit: 0, debit_base: 5000000, credit_base: 0, balance: -485000000, nature: "بستانکار", balance_base: -485000000 },
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
	assert.equal(group.rows[0].qty * group.rows[0].rate, group.rows[0].debit);
	assert.deepEqual([group.rows[0].first, group.rows[1].last], [true, true]);

	const base_total = group.rows.reduce((sum, row) => sum + row.debit_base, 0);
	assert.equal(base_total, 215000000, "split rows add up to the GL base debit too");
	assert.equal(group.rows[0].rate_base, 21000000);

	const html = pae_ledger_view.group_rows(group, pae_ledger_view.columns(CONTEXT), CONTEXT);
	assert.equal((html.match(/href="\/desk\/sales-invoice\/ACC-SINV-2026-00012"/g) || []).length, 3, "the document repeats on every row, the posting voucher once in «جزئیات»");
	assert.equal((html.match(/sp-detail-btn/g) || []).length, 1, "one details button per GL line");
	assert.equal((html.match(/Debtors - SP/g) || []).length, 2, "the GL line's account is named once in «جزئیات» (text and tooltip)");
	assert.equal(html.includes("CAM-1"), false, "no item code in the main table");
	assert.equal(html.includes("عدد"), false, "no unit of measure in the main table");
	assert.equal(html.includes("aria-expanded"), false, "no inline expansion");
}

// Page 2 columns, in report order: plain columns are GL base amounts, «ارزی» ones GL account-currency amounts.
{
	const columns = pae_ledger_view.columns(CONTEXT);
	assert.deepEqual(
		columns.map((column) => column.label),
		["ردیف", "تاریخ", "نوع برگه", "شرح", "عنوان قلم", "مقدار", "فی", "بدهکار", "بستانکار", "مانده", "فی ارزی", "بدهکار ارزی", "بستانکار ارزی", "مانده ارزی", "جزئیات"]
	);
	assert.equal(columns.some((column) => column.key === "posting_rate"), false, "no rate derived from GL amounts");
	assert.equal(columns.find((column) => column.key === "document").label, "نوع برگه");
	assert.equal(columns.some((column) => column.key === "detail_ref"), false);
	assert.equal(columns.some((column) => column.sort), false, "no visual sort: rows stay chronological");
	assert.equal(pae_ledger_view.head(columns).includes("data-sort"), false);
}

// «جزئیات»: the GL voucher (SP-POST / JE / invoice), linked when readable, with the row reference below.
{
	const receipt = {
		gl_entry: "GL-9",
		posting_date: "2026-05-02",
		voucher_label: "رسید",
		document_number: "SP-REC-2026-00019",
		document: { doctype: "SmartProcess Accounting Document", name: "SP-REC-2026-00019" },
		voucher_no: "SP-POST-2026-00007",
		voucher: { doctype: "SmartProcess Accounting Posting", name: "SP-POST-2026-00007" },
		detail_ref: "ردیف 1 · پرداخت‌کننده",
		debit: 0,
		credit: 700000000,
		balance: -700000000,
		components: [],
	};
	const [group] = pae_ledger_rows.groups([receipt], 0, true);
	const cell = pae_ledger_view.cell("actions", group.rows[0], CONTEXT);
	assert.match(cell, /href="\/desk\/smartprocess-accounting-posting\/SP-POST-2026-00007"[^>]*>SP-POST-2026-00007<\/a>/);
	assert.match(cell, /sp-voucher-detail">ردیف 1 · پرداخت‌کننده/);
	assert.match(cell, /sp-detail-btn/);
	const hidden = pae_ledger_rows.groups([{ ...receipt, voucher: null }], 0, true)[0];
	const plain = pae_ledger_view.cell("actions", hidden.rows[0], CONTEXT);
	assert.equal(plain.includes("<a "), false, "an unreadable posting stays plain text");
	assert.match(plain, /SP-POST-2026-00007/);
	assert.match(pae_ledger_view.cell("document", group.rows[0], CONTEXT), /رسید<\/span> - <a [^>]*>SP-REC-2026-00019<\/a>/);
}

// Server filters: the status line reports the server totals and keeps the chronological balance note.
{
	assert.equal(pae_ledger_rows.is_filtered({ search: " ", side: "" }), false);
	assert.equal(pae_ledger_rows.is_filtered({ search: "", side: "debit" }), true);
	assert.equal(pae_ledger_view.status({ search: "", side: "" }, null, "IRR"), "");
	const status = pae_ledger_view.status({ search: "2CD", side: "" }, { row_count: 3, debit: 215, credit: 0, debit_base: 9000, credit_base: 0 }, "USD", "IRR");
	assert.match(status, /3 ردیف دفتر کل مطابق فیلتر/);
	assert.match(status, />215</);
	assert.match(status, />9000</);
	assert.match(status, /به ترتیب زمانی/);
	assert.equal(pae_ledger_view.toolbar({ search: "a\"b", side: "credit" }).includes('value="a&quot;b"'), true);
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
	const html = pae_ledger_view.cell("description", group.rows[0], CONTEXT);
	assert.match(html, /ارز ثبت: USD/);
	assert.match(html, /ارز سند: EUR/);
	assert.match(pae_ledger_view.currency_cell("IRR", 3), /3 ردیف با ارز دیگر/);
	assert.equal(pae_ledger_view.currency_cell("IRR", 0), "IRR");
}

// Opening and totals rows put the label in the document column.
{
	const columns = pae_ledger_view.columns(CONTEXT);
	const values = { label: "جمع گردش کل دوره", debit: 5, credit: 0, balance: 15, debit_base: 500, credit_base: 0, balance_base: 1500 };
	const html = pae_ledger_view.balance_row("sp-total-row", columns, CONTEXT, values);
	const cells = html.match(/<td[^>]*>.*?<\/td>/g);
	const at = (key) => cells[columns.findIndex((column) => column.key === key)];
	assert.equal(cells.length, columns.length);
	assert.match(at("document"), /جمع گردش کل دوره/);
	assert.match(at("debit"), />5</);
	assert.match(at("credit"), />0</);
	assert.match(at("balance"), />15</);
	assert.match(at("debit_base"), />500</);
	assert.match(at("balance_base"), />1500</);
}

// Page 1: party name only, the account currency, then base and account-currency columns; totals per currency.
{
	const columns = pae_ledger_view.overview_columns();
	assert.deepEqual(
		columns.map((column) => column.label),
		["طرف حساب", "ارز حساب", "گردش بدهکار", "گردش بستانکار", "مانده", "گردش بدهکار ارزی", "گردش بستانکار ارزی", "مانده ارزی"]
	);
	const row = { party: "CUST-0001", party_name: "Customer One", currency: "USD", period_debit_base: 900, period_credit_base: 0, closing_base: 900, period_debit: 10, period_credit: 0, closing: 10 };
	const html = columns.map((column) => pae_ledger_view.overview_cell(column.key, row, "IRR")).join("");
	assert.match(html, /Customer One/);
	assert.equal(html.includes("CUST-0001"), false, "the party code is not repeated under the name");
	assert.equal(columns.some((column) => column.key === "account"), false, "no account column on page 1");
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

// Details dialog body: read-only summary; item code and unit live here, not in the table.
{
	const detail = {
		title: "فاکتور فروش",
		document: { doctype: "Sales Invoice", name: "ACC-SINV-2026-00012" },
		summary: [
			{ label: "مبلغ کل", kind: "amount", value: 210000000, currency: "IRR" },
			{ label: "برگشت از سند", kind: "link", value: "ACC-SINV-2026-00001", doctype: "Sales Invoice" },
		],
		sections: [
			{
				title: "اقلام",
				columns: [
					{ key: "item_name", label: "نام کالا", kind: "text" },
					{ key: "item_code", label: "کد کالا", kind: "text" },
					{ key: "qty", label: "مقدار", kind: "number" },
					{ key: "uom", label: "واحد", kind: "text" },
				],
				rows: [{ item_name: "DS-2CD2347G2-L (2.8mm)", item_code: "CAM-1", qty: 10, uom: "عدد" }],
			},
		],
		related: [],
		technical: [],
	};
	const html = pae_detail_view.html(detail);
	assert.equal(pae_detail_view.title(detail), "فاکتور فروش — ACC-SINV-2026-00012");
	assert.match(html, /CAM-1/, "the item code appears in the details");
	assert.match(html, /عدد/, "the unit appears in the details");
	assert.match(html, /href="\/desk\/sales-invoice\/ACC-SINV-2026-00001"/);
	assert.equal(html.includes("باز کردن سند کامل"), false, "the dialog's primary action opens the document");
	assert.equal(html.includes("<input"), false, "details are read-only");
	assert.equal("detail_row" in pae_ledger_view, false, "no inline detail rows");
}

console.log("party account explorer UI tests passed");
