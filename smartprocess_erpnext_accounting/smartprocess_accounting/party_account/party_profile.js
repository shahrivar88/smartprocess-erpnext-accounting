// Form behaviour shared by custom ERPNext Party DocTypes (see party_profile.py):
// standard Contact/Address panels, the Party Account grid, and a read-only panel of
// GL balances per Company + Account with the related documents.
const spPartyProfile = {
	METHOD: "smartprocess_erpnext_accounting.smartprocess_accounting.party_account.party_profile.get_party_profile",
	EXPLORER: "party-account-explorer",
	EMPTY: "-",
	PANEL: "balances_html",

	LINK_QUERIES: {
		primary_contact: "frappe.contacts.doctype.contact.contact.contact_query",
		primary_address: "frappe.contacts.doctype.address.address.address_query",
	},

	// Each field may be missing until the DocType schema is synced.
	setup(frm) {
		if (frm.fields_dict.accounts) {
			frm.set_query("account", "accounts", (doc, cdt, cdn) => {
				const row = locals[cdt][cdn];
				return {
					filters: {
						company: row.company,
						is_group: 0,
						disabled: 0,
						account_type: frm.doc.__onload?.party_account_type || ["in", ["Receivable", "Payable"]],
					},
				};
			});
		}
		if (frm.fields_dict.default_currency) {
			frm.set_query("default_currency", () => ({ filters: { enabled: 1 } }));
		}
		for (const [field, query] of Object.entries(this.LINK_QUERIES)) {
			if (frm.fields_dict[field]) {
				frm.set_query(field, () => ({ query, filters: { link_doctype: frm.doctype, link_name: frm.doc.name } }));
			}
		}
	},

	refresh(frm) {
		frappe.dynamic_link = { doc: frm.doc, fieldname: "name", doctype: frm.doctype };
		frm.fields_dict.accounts?.grid.update_docfield_property("advance_account", "hidden", 1);
		if (frm.is_new()) {
			frappe.contacts.clear_address_and_contact(frm);
			return;
		}
		if (frm.fields_dict.contact_html) {
			frappe.contacts.render_address_and_contact(frm);
		}
		frm.add_custom_button(__("دفتر کل"), () => this.openGeneralLedger(frm), __("نمایش"));
		frm.add_custom_button(__("گردش حساب"), () => this.openExplorer(frm), __("نمایش"));
		return this.load(frm);
	},

	async load(frm) {
		const panel = frm.fields_dict[this.PANEL];
		if (!panel) {
			return;
		}
		panel.$wrapper.html(`<div class="text-muted small">${__("در حال بارگذاری...")}</div>`);
		const profile = await frappe.xcall(this.METHOD, { party_type: frm.doctype, party: frm.doc.name }, "GET");
		panel.$wrapper.html(this.html(profile, this.tools()));
		panel.$wrapper.find("[data-sp-ledger]").on("click", (event) => {
			const row = profile.balances[Number(event.currentTarget.dataset.spLedger)];
			this.openExplorer(frm, row);
		});
	},

	openGeneralLedger(frm) {
		frappe.set_route("query-report", "General Ledger", { party_type: frm.doctype, party: frm.doc.name });
	},

	// Whole history of one Company + Account; the explorer itself checks permissions.
	openExplorer(frm, row) {
		if (!row) {
			frappe.set_route(this.EXPLORER, "list");
			return;
		}
		frappe.set_route(this.EXPLORER, "ledger", ...this.ledgerRoute(frm.doctype, frm.doc.name, row));
	},

	ledgerRoute(partyType, party, row) {
		return [row.company, partyType, party, row.currency, row.account, null, null].map((value) => value || this.EMPTY);
	},

	tools() {
		return {
			escape: frappe.utils.escape_html,
			money: (value, currency) => format_currency(value, currency),
			date: (value) => frappe.datetime.str_to_user(value),
			url: (doctype, name) => frappe.utils.get_form_link(doctype, name),
		};
	},

	html(profile, tools) {
		return [this.balancesHtml(profile, tools), this.documentsHtml(profile.documents, __("آخرین اسناد ثبت‌شده"), tools), this.documentsHtml(profile.drafts, __("پیش‌نویس‌ها"), tools)].join("");
	},

	balancesHtml(profile, tools) {
		if (profile.balances === null) {
			return `<p class="text-muted">${__("برای دیدن مانده‌ها اجازه مشاهده دفتر کل لازم است.")}</p>`;
		}
		if (!profile.balances.length) {
			return `<p class="text-muted">${__("تا {0} گردشی در دفتر کل ثبت نشده است.", [tools.escape(tools.date(profile.as_of))])}</p>`;
		}
		const rows = profile.balances.map((row, index) => `<tr>
			<td>${tools.escape(row.company)}</td>
			<td>${tools.escape(row.account)}</td>
			<td>${tools.escape(row.currency)}</td>
			<td class="text-right">${tools.money(row.closing, row.currency)}</td>
			<td class="text-right">${tools.money(row.closing_base, row.company_currency)}</td>
			<td>${tools.escape(row.nature)}</td>
			<td>${tools.escape(tools.date(row.last_posting_date))}</td>
			<td><button class="btn btn-xs btn-default" data-sp-ledger="${index}">${__("گردش حساب")}</button></td>
		</tr>`);
		return `<p class="text-muted small">${__("مانده تا تاریخ {0}، جدا برای هر شرکت و حساب. مبالغ تبدیل نمی‌شوند.", [tools.escape(tools.date(profile.as_of))])}</p>
		<table class="table table-bordered table-sm">
			<thead><tr>
				<th>${__("شرکت")}</th><th>${__("حساب")}</th><th>${__("ارز حساب")}</th>
				<th>${__("مانده به ارز حساب")}</th><th>${__("مانده به ارز شرکت")}</th>
				<th>${__("ماهیت")}</th><th>${__("آخرین گردش")}</th><th></th>
			</tr></thead>
			<tbody>${rows.join("")}</tbody>
		</table>`;
	},

	documentsHtml(documents, title, tools) {
		if (!documents?.length) {
			return "";
		}
		const items = documents.map((doc) => {
			const name = tools.escape(doc.name);
			const link = doc.readable === false ? name : `<a href="${tools.url(doc.doctype, doc.name)}">${name}</a>`;
			const date = doc.posting_date ? ` · ${tools.escape(tools.date(doc.posting_date))}` : "";
			return `<li>${tools.escape(doc.label)} ${link}${date}</li>`;
		});
		return `<h6>${title}</h6><ul class="list-unstyled">${items.join("")}</ul>`;
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = spPartyProfile;
}
