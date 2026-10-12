// Pure party profile UI tests: Frappe is stubbed, nothing touches a site.
const assert = require("node:assert/strict");
const path = require("node:path");

globalThis.__ = (text, args) => (args ? text.replace(/\{(\d+)\}/g, (_match, index) => args[index]) : text);
const routes = [];
const queries = {};
globalThis.locals = { "Party Account": { row1: { company: "C1" } } };
globalThis.frappe = {
	set_route: (...args) => routes.push(args),
	contacts: { clear_address_and_contact: () => routes.push(["cleared"]) },
};

const spPartyProfile = require(path.join(__dirname, "..", "party_account", "party_profile.js"));
const DOCTYPE = "SmartProcess Financial Intermediary";
const tools = {
	escape: (value) => String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"),
	money: (value, currency) => `${value} ${currency}`,
	date: (value) => value || "",
	url: (doctype, name) => `/app/${doctype}/${name}`,
};

function make_form(doc = {}, fields = ["accounts", "primary_contact", "primary_address"]) {
	return {
		doctype: DOCTYPE,
		doc: { name: "P1", ...doc },
		fields_dict: Object.fromEntries(fields.map((field) => [field, {}])),
		set_query(field, table, query) {
			queries[field] = typeof table === "function" ? table : query;
		},
	};
}

// Account picker: same company, ledger accounts of the Party Type's account type only.
{
	const frm = make_form({ __onload: { party_account_type: "Receivable" } });
	spPartyProfile.setup(frm);
	const filters = queries.account(frm.doc, "Party Account", "row1").filters;
	assert.deepEqual(filters, { company: "C1", is_group: 0, disabled: 0, account_type: "Receivable" });
	assert.deepEqual(queries.primary_contact().filters, { link_doctype: DOCTYPE, link_name: "P1" });
	assert.equal(queries.primary_address().query, "frappe.contacts.doctype.address.address.address_query");
}

// Before the schema sync the form has none of these fields; setup sets no query.
{
	for (const field of Object.keys(queries)) {
		delete queries[field];
	}
	spPartyProfile.setup(make_form({}, []));
	assert.deepEqual(Object.keys(queries), []);
}

// The ledger deep link keeps Company, Party, Account currency and Account; empty dates stay "-".
{
	const route = spPartyProfile.ledgerRoute(DOCTYPE, "P1", { company: "C1", currency: "USD", account: "Debtors USD" });
	assert.deepEqual(route, ["C1", DOCTYPE, "P1", "USD", "Debtors USD", "-", "-"]);
	spPartyProfile.openExplorer(make_form(), { company: "C1", currency: "USD", account: "Debtors USD" });
	assert.deepEqual(routes.at(-1), ["party-account-explorer", "ledger", ...route]);
}

// One row per Company + Account, each in its own currency; nothing is converted or summed.
{
	const html = spPartyProfile.html(
		{
			as_of: "2026-10-12",
			balances: [
				{ company: "C1", company_currency: "IRR", account: "Debtors", currency: "IRR", closing: 10, closing_base: 10, nature: "بدهکار" },
				{ company: "C1", company_currency: "IRR", account: "Debtors USD", currency: "USD", closing: -2, closing_base: -1800, nature: "بستانکار" },
			],
			documents: [
				{ doctype: "SmartProcess Accounting Document", name: "RR-1", label: "رسید", posting_date: "2026-10-01", readable: true },
				{ doctype: "Journal Entry", name: "<JV-1>", label: "سند حسابداری", posting_date: "2026-10-02", readable: false },
			],
			drafts: [],
		},
		tools,
	);
	assert.match(html, /10 IRR/);
	assert.match(html, /-2 USD/);
	assert.match(html, /-1800 IRR/);
	assert.equal((html.match(/data-sp-ledger=/g) || []).length, 2);
	assert.match(html, /href="\/app\/SmartProcess Accounting Document\/RR-1"/);
	assert.doesNotMatch(html, /href="[^"]*JV-1/);
	assert.match(html, /&lt;JV-1&gt;/);
	assert.doesNotMatch(html, /پیش‌نویس‌ها/);
}

// No GL permission and no GL rows have their own messages.
{
	assert.match(spPartyProfile.html({ as_of: "2026-10-12", balances: null, documents: [], drafts: [] }, tools), /اجازه مشاهده دفتر کل/);
	assert.match(spPartyProfile.html({ as_of: "2026-10-12", balances: [], documents: [], drafts: [] }, tools), /گردشی در دفتر کل ثبت نشده/);
}

console.log("party profile UI tests passed");
