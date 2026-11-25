{% include "smartprocess_erpnext_accounting/smartprocess_accounting/page/settlement_workbench/workbench_logic.js" %}

frappe.pages["settlement-workbench"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("تطبیق و تسویه"),
		single_column: true,
	});
	frappe.settlement_workbench = new SettlementWorkbench(page);
};

class SettlementWorkbench {
	constructor(page) {
		this.page = page;
		this.entries = { invoices: [], payments: [] };
		this.allocation = [];
		this.busy = false;
		this.makeFilters();
		this.makeLayout();
		this.page.set_primary_action(__("بارگذاری"), () => this.load());
		this.page.add_inner_button(__("پیشنهاد FIFO"), () => this.suggest());
		this.page.add_inner_button(__("ثبت تخصیص"), () => this.reconcile());
		this.page.add_inner_button(__("تهاتر"), () => this.offset());
		this.page.add_inner_button(__("لغو تطبیق"), () => this.unreconcile());
		this.page.add_menu_item(__("اعتبارهای نیازمند بررسی"), () => {
			frappe.set_route("query-report", "Unallocatable Credits");
		});
		frappe.xcall(spSettlementWorkbench.method("require_settlement_access"));
	}

	makeFilters() {
		this.page.company = this.page.add_field({
			fieldname: "company",
			label: __("شرکت"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_default("company"),
		});
		this.page.party_type = this.page.add_field({
			fieldname: "party_type",
			label: __("نوع طرف‌حساب"),
			fieldtype: "Select",
			options: "Customer\nSupplier",
			reqd: 1,
			default: "Customer",
		});
		this.page.party = this.page.add_field({
			fieldname: "party",
			label: __("طرف‌حساب"),
			fieldtype: "Dynamic Link",
			options: "party_type",
			reqd: 1,
			get_query: () => ({ filters: { disabled: 0 } }),
		});
		this.page.account = this.page.add_field({
			fieldname: "account",
			label: __("حساب"),
			fieldtype: "Link",
			options: "Account",
			reqd: 1,
			get_query: () => {
				const partyType = this.page.party_type.get_value();
				return {
					filters: {
						company: this.page.company.get_value(),
						is_group: 0,
						account_type: partyType === "Supplier" ? "Payable" : "Receivable",
					},
				};
			},
		});
		this.page.currency = this.page.add_field({
			fieldname: "currency",
			label: __("ارز"),
			fieldtype: "Link",
			options: "Currency",
		});
	}

	makeLayout() {
		this.page.main.html(`
			<p class="text-muted">${frappe.utils.escape_html(__("فاکتورهای باز و دریافت‌های تخصیص‌نیافته از مسیر استاندارد تطبیق ERPNext خوانده می‌شوند."))}</p>
			<div class="sp-settle-summary"></div>
			<h5>${frappe.utils.escape_html(__("فاکتورهای باز"))}</h5>
			<div class="sp-settle-invoices"></div>
			<h5>${frappe.utils.escape_html(__("دریافت و پرداخت تخصیص‌نیافته"))}</h5>
			<div class="sp-settle-payments"></div>
			<h5>${frappe.utils.escape_html(__("پیشنهاد تخصیص"))}</h5>
			<div class="sp-settle-allocation"></div>
		`);
	}

	async load() {
		const filters = spSettlementWorkbench.filtersOf(this.page);
		if (!spSettlementWorkbench.filtersReady(filters)) {
			frappe.msgprint(__("شرکت، طرف‌حساب و حساب را کامل کنید."));
			return;
		}
		if (this.busy) {
			return;
		}
		this.busy = true;
		try {
			this.entries = await frappe.xcall(spSettlementWorkbench.method("load_entries"), { filters });
			this.allocation = [];
			this.render();
		} finally {
			this.busy = false;
		}
	}

	async suggest() {
		if (!this.entries.invoices.length || !this.entries.payments.length) {
			await this.load();
		}
		this.allocation = await frappe.xcall(spSettlementWorkbench.method("preview_allocations"), {
			filters: spSettlementWorkbench.filtersOf(this.page),
		});
		this.render();
	}

	async reconcile() {
		if (this.busy) {
			return;
		}
		const filters = spSettlementWorkbench.filtersOf(this.page);
		if (!spSettlementWorkbench.filtersReady(filters)) {
			frappe.msgprint(__("شرکت، طرف‌حساب و حساب را کامل کنید."));
			return;
		}
		if (!this.allocation.length) {
			this.allocation = spSettlementWorkbench.allocationRows(this.entries.invoices, this.entries.payments);
		}
		if (!this.allocation.length) {
			frappe.msgprint(__("تخصیصی برای ثبت وجود ندارد."));
			return;
		}
		const rows = this.allocation;
		const dialog = new frappe.ui.Dialog({
			title: __("تأیید ثبت تخصیص"),
			size: "large",
			fields: [{ fieldtype: "HTML", fieldname: "summary", options: this.allocationHtml(rows) }],
			primary_action_label: __("ثبت تخصیص"),
			primary_action: async () => {
				if (this.busy) {
					return;
				}
				this.busy = true;
				try {
					this.entries = await frappe.xcall(spSettlementWorkbench.method("reconcile_entries"), {
						filters,
						allocations: rows,
					});
					this.allocation = [];
					this.render();
					dialog.hide();
					frappe.show_alert({ message: __("تخصیص ثبت شد."), indicator: "green" });
				} finally {
					this.busy = false;
				}
			},
		});
		dialog.show();
	}

	allocationHtml(rows) {
		const display = spSettlementWorkbench.allocationDisplayRows(rows);
		const totals = spSettlementWorkbench.allocationTotals(rows);
		const head = [__("دریافت/پرداخت"), __("فاکتور"), __("مبلغ تخصیص"), __("ارز")]
			.map((title) => `<th>${frappe.utils.escape_html(String(title))}</th>`)
			.join("");
		const body = display
			.map(
				(row) =>
					`<tr><td>${frappe.utils.escape_html(row.payment)}</td>` +
					`<td>${frappe.utils.escape_html(row.invoice)}</td>` +
					`<td>${frappe.utils.escape_html(String(row.amount))}</td>` +
					`<td>${frappe.utils.escape_html(row.currency)}</td></tr>`,
			)
			.join("");
		const total = Object.entries(totals.by_currency)
			.map(([currency, amount]) => `${frappe.utils.escape_html(String(amount))} ${frappe.utils.escape_html(currency)}`)
			.join(" · ");
		return (
			`<p>${frappe.utils.escape_html(__("{0} ردیف تخصیص ثبت می‌شود.", [String(totals.count)]))}</p>` +
			`<table class="table table-bordered"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>` +
			`<p>${frappe.utils.escape_html(__("جمع"))}: ${total}</p>`
		);
	}

	offset() {
		const filters = spSettlementWorkbench.filtersOf(this.page);
		const dialog = new frappe.ui.Dialog({
			title: __("تهاتر بدون بانک"),
			fields: [
				{ fieldname: "posting_date", label: __("تاریخ"), fieldtype: "Date", reqd: 1, default: frappe.datetime.get_today() },
				{ fieldname: "receivable_party", label: __("مشتری"), fieldtype: "Link", options: "Customer", reqd: 1 },
				{ fieldname: "receivable_account", label: __("حساب دریافتنی"), fieldtype: "Link", options: "Account", reqd: 1 },
				{ fieldname: "receivable_invoice", label: __("فاکتور فروش"), fieldtype: "Link", options: "Sales Invoice", reqd: 1 },
				{ fieldname: "payable_party", label: __("تأمین‌کننده"), fieldtype: "Link", options: "Supplier", reqd: 1 },
				{ fieldname: "payable_account", label: __("حساب پرداختنی"), fieldtype: "Link", options: "Account", reqd: 1 },
				{ fieldname: "payable_invoice", label: __("فاکتور خرید"), fieldtype: "Link", options: "Purchase Invoice", reqd: 1 },
				{ fieldname: "amount", label: __("مبلغ تهاتر"), fieldtype: "Currency" },
			],
			primary_action_label: __("ثبت تهاتر"),
			primary_action: async (values) => {
				if (this.busy) {
					return;
				}
				const payload = {
					...values,
					company: filters.company,
					company_currency: frappe.defaults.get_default("currency"),
				};
				this.busy = true;
				try {
					const preview = await frappe.xcall(spSettlementWorkbench.method("preview_journal_offset"), { payload });
					const result = await frappe.xcall(spSettlementWorkbench.method("submit_journal_offset"), { payload });
					dialog.hide();
					frappe.set_route("Form", "Journal Entry", result.name);
					frappe.show_alert({ message: __("تهاتر ثبت شد: {0}", [preview.amount]), indicator: "green" });
				} finally {
					this.busy = false;
				}
			},
		});
		dialog.show();
	}

	unreconcile() {
		const filters = spSettlementWorkbench.filtersOf(this.page);
		const dialog = new frappe.ui.Dialog({
			title: __("لغو تطبیق استاندارد"),
			fields: [
				{ fieldname: "doctype", label: __("نوع سند"), fieldtype: "Select", options: "Sales Invoice\nPurchase Invoice\nPayment Entry\nJournal Entry", reqd: 1 },
				{ fieldname: "name", label: __("شماره سند"), fieldtype: "Data", reqd: 1 },
			],
			primary_action_label: __("نمایش تخصیص‌ها"),
			primary_action: async (values) => {
				if (this.busy) {
					return;
				}
				this.busy = true;
				try {
					const links = await frappe.xcall(spSettlementWorkbench.method("load_links"), {
						company: filters.company,
						doctype: values.doctype,
						name: values.name,
					});
					if (!links.length) {
						frappe.msgprint(__("تخصیص فعالی برای این سند نیست."));
						return;
					}
					dialog.hide();
					const selections = links.map((row) => ({
						company: filters.company,
						voucher_type: values.doctype === "Payment Entry" || values.doctype === "Journal Entry" ? values.doctype : row.reference_doctype,
						voucher_no: values.doctype === "Payment Entry" || values.doctype === "Journal Entry" ? values.name : row.reference_name,
						against_voucher_type: values.doctype === "Payment Entry" || values.doctype === "Journal Entry" ? row.reference_doctype : values.doctype,
						against_voucher_no: values.doctype === "Payment Entry" || values.doctype === "Journal Entry" ? row.reference_name : values.name,
					}));
					this.confirmUnreconcile(values, links, selections);
				} finally {
					this.busy = false;
				}
			},
		});
		dialog.show();
	}

	confirmUnreconcile(values, links, selections) {
		const head = [__("سند"), __("در برابر"), __("مبلغ")]
			.map((title) => `<th>${frappe.utils.escape_html(String(title))}</th>`)
			.join("");
		const body = links
			.map(
				(row) =>
					`<tr><td>${frappe.utils.escape_html(row.reference_doctype || "")} ${frappe.utils.escape_html(row.reference_name || "")}</td>` +
					`<td>${frappe.utils.escape_html(values.doctype)} ${frappe.utils.escape_html(values.name)}</td>` +
					`<td>${frappe.utils.escape_html(String(row.allocated_amount ?? row.amount ?? ""))}</td></tr>`,
			)
			.join("");
		const dialog = new frappe.ui.Dialog({
			title: __("تأیید لغو تطبیق"),
			size: "large",
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "summary",
					options:
						`<p>${frappe.utils.escape_html(__("{0} تخصیص لغو می‌شود.", [String(links.length)]))}</p>` +
						`<table class="table table-bordered"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`,
				},
			],
			primary_action_label: __("لغو تطبیق"),
			primary_action: async () => {
				if (this.busy) {
					return;
				}
				this.busy = true;
				try {
					await frappe.xcall(spSettlementWorkbench.method("unreconcile_entries"), { selections });
					dialog.hide();
					frappe.show_alert({ message: __("لغو تطبیق انجام شد."), indicator: "green" });
					this.load();
				} finally {
					this.busy = false;
				}
			},
		});
		dialog.show();
	}

	render() {
		const summary = this.page.main.find(".sp-settle-summary");
		const currency = this.summaryCurrency();
		summary.html(`
			<p>${__("مانده فاکتورها")}: ${frappe.utils.escape_html(this.amount(this.entries.outstanding || 0, currency))}</p>
			<p>${__("اعتبار آزاد")}: ${frappe.utils.escape_html(this.amount(this.entries.unallocated || 0, currency))}</p>
		`);
		this.page.main.find(".sp-settle-invoices").html(this.table(
			[__("فاکتور"), __("مانده"), __("ارز")],
			(this.entries.invoices || []).map((row) => [
				this.link(row.invoice_type, row.invoice_number),
				this.amount(row.outstanding_amount, row.currency),
				row.currency,
			]),
		));
		this.page.main.find(".sp-settle-payments").html(this.table(
			[__("سند"), __("مبلغ آزاد"), __("سند مادر")],
			(this.entries.payments || []).map((row) => [
				this.link(row.reference_type, row.reference_name),
				this.amount(row.amount, row.currency),
				row.source_document ? this.link("SmartProcess Accounting Document", row.source_document) : "",
			]),
		));
		this.page.main.find(".sp-settle-allocation").html(this.table(
			[__("دریافت"), __("فاکتور"), __("تخصیص")],
			(this.allocation || []).map((row) => [
				row.reference_name,
				row.invoice_number,
				this.amount(row.allocated_amount, row.currency),
			]),
		));
	}

	summaryCurrency() {
		const first = (this.entries.invoices || [])[0] || (this.entries.payments || [])[0];
		return first?.currency || "";
	}

	amount(value, currency) {
		if (value === null || value === undefined || value === "") {
			return "";
		}
		return format_currency(value, currency || undefined);
	}

	table(headers, rows) {
		const head = headers.map((title) => `<th>${frappe.utils.escape_html(String(title))}</th>`).join("");
		const body = (rows || []).map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("");
		const empty = `<tr><td colspan="${headers.length}" class="text-muted">${frappe.utils.escape_html(
			__("موردی یافت نشد"),
		)}</td></tr>`;
		return (
			`<div class="table-responsive"><table class="table table-bordered">` +
			`<thead><tr>${head}</tr></thead><tbody>${body || empty}</tbody></table></div>`
		);
	}

	link(doctype, name) {
		if (!name) {
			return "";
		}
		const slug = String(doctype).toLowerCase().replace(/ /g, "-");
		return `<a href="${frappe.utils.escape_html(`/app/${slug}/${encodeURIComponent(name)}`)}">${frappe.utils.escape_html(name)}</a>`;
	}
}
