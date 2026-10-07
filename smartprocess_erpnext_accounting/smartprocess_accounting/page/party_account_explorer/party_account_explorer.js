{% include "smartprocess_erpnext_accounting/smartprocess_accounting/page/party_account_explorer/explorer/format.js" %}
{% include "smartprocess_erpnext_accounting/smartprocess_accounting/page/party_account_explorer/explorer/ledger_rows.js" %}
{% include "smartprocess_erpnext_accounting/smartprocess_accounting/page/party_account_explorer/explorer/column_prefs.js" %}
{% include "smartprocess_erpnext_accounting/smartprocess_accounting/page/party_account_explorer/explorer/ledger_view.js" %}
{% include "smartprocess_erpnext_accounting/smartprocess_accounting/page/party_account_explorer/explorer/detail_view.js" %}

const PAE_API = "smartprocess_erpnext_accounting.smartprocess_accounting.party_account.";
const PAE_ROUTE = "party-account-explorer";
const PAE_LEDGER_KEYS = ["company", "party_type", "party", "account", "from_date", "to_date"];
const PAE_PAGE_LENGTH = 100;
const PAE_EMPTY = "-";

frappe.pages[PAE_ROUTE].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("گردش و مانده طرف حساب"),
		single_column: true,
	});
	frappe.party_account_explorer = new PartyAccountExplorer(page);
};

frappe.pages[PAE_ROUTE].on_page_show = function () {
	if (frappe.party_account_explorer) {
		frappe.party_account_explorer.show_route();
	}
};

class PartyAccountExplorer {
	constructor(page) {
		this.page = page;
		this.overview_page = 1;
		this.overview = null;
		this.ledger = null;
		this.ledger_key = null;
		this.cursors = [null];
		this.page_index = 0;
		this.opened_from_overview = false;
		this.prefs = new PaeColumnPrefs(frappe.model.user_settings);
		this.reset_ledger_view();
		this.make_filters();
		this.make_layout();
		this.page.set_primary_action(__("نمایش"), () => this.refresh());
		this.page.add_menu_item(__("خروجی اکسل"), () => this.export_file("xlsx"));
		this.page.add_menu_item(__("خروجی PDF"), () => this.export_file("pdf"));
		this.ensure_desk_sidebar();
		frappe.router.on("change", () => {
			if (frappe.get_route()[0] === PAE_ROUTE) {
				this.show_route();
			}
		});
		this.ready = Promise.all([this.load_defaults(), this.prefs.load()]);
		this.show_route();
	}

	reset_ledger_view() {
		this.view_state = { query: "", side: "", sort_key: null, sort_dir: null };
		this.details = new Map();
		this.open_details = new Set();
	}

	make_filters() {
		const overview_change = () => !this.muted && this.mode === "overview" && this.refresh_overview(1);
		this.company = this.page.add_field({
			fieldname: "company",
			label: __("شرکت"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_default("company"),
			change: () => {
				if (this.muted) {
					return;
				}
				this.ready = this.load_defaults();
				this.ready.then(() => this.mode === "overview" && this.refresh_overview(1));
			},
		});
		this.party_type = this.page.add_field({
			fieldname: "party_type",
			label: __("نوع طرف حساب"),
			fieldtype: "Select",
			options: [
				{ value: "Customer", label: __("مشتری") },
				{ value: "Supplier", label: __("تأمین‌کننده") },
			],
			default: "Customer",
			change: overview_change,
		});
		this.party = this.page.add_field({
			fieldname: "party",
			label: __("جستجوی طرف حساب (نام یا کد)"),
			fieldtype: "Data",
			change: overview_change,
		});
		this.account = this.page.add_field({
			fieldname: "account",
			label: __("حساب"),
			fieldtype: "Link",
			options: "Account",
			get_query: () => ({ filters: { company: this.company.get_value(), is_group: 0 } }),
			change: overview_change,
		});
		this.currency = this.page.add_field({
			fieldname: "currency",
			label: __("ارز حساب"),
			fieldtype: "Select",
			options: [""],
			change: overview_change,
		});
		this.from_date = this.page.add_field({
			fieldname: "from_date",
			label: __("از تاریخ"),
			fieldtype: "Date",
			change: () => this.on_period_change(),
		});
		this.to_date = this.page.add_field({
			fieldname: "to_date",
			label: __("تا تاریخ"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			change: () => this.on_period_change(),
		});
		this.hide_zero = this.page.add_field({
			fieldname: "hide_zero",
			label: __("مخفی کردن مانده صفر"),
			fieldtype: "Check",
			default: 1,
			change: overview_change,
		});
		this.show_items = this.page.add_field({
			fieldname: "show_items",
			label: __("نمایش اقلام فاکتور"),
			fieldtype: "Check",
			default: 1,
			change: () => this.mode === "ledger" && this.ledger && this.render_ledger(),
		});
	}

	make_layout() {
		this.$wrap = $('<div class="sp-party-explorer"></div>').appendTo(this.page.main);
		this.$overview = $('<div class="sp-overview"></div>').appendTo(this.$wrap);
		this.$ledger = $('<div class="sp-ledger"></div>').appendTo(this.$wrap);
		this.$wrap.on("click", "a.sp-doc-link", (event) => {
			if (event.ctrlKey || event.metaKey || event.shiftKey || event.button === 1) {
				return;
			}
			event.preventDefault();
			event.stopPropagation();
			const $link = $(event.currentTarget);
			frappe.set_route("Form", $link.attr("data-doctype"), $link.attr("data-name"));
		});
		this.$overview.on("click", "tr.sp-row-link", (event) => {
			this.open_ledger(this.overview.rows[cint($(event.currentTarget).attr("data-index"))]);
		});
		this.$overview.on("click", ".sp-page-prev", () => this.refresh_overview(this.overview_page - 1));
		this.$overview.on("click", ".sp-page-next", () => this.refresh_overview(this.overview_page + 1));
		this.$ledger.on("click", ".sp-detail-btn", (event) => this.toggle_detail($(event.currentTarget).closest("tr").attr("data-gl")));
		this.$ledger.on("click", "th.sp-sortable", (event) => {
			Object.assign(this.view_state, pae_ledger_rows.next_sort(this.view_state, $(event.currentTarget).attr("data-sort")));
			this.render_ledger_table();
		});
		this.$ledger.on("input", ".sp-ledger-search", (event) => {
			clearTimeout(this.search_timer);
			this.search_timer = setTimeout(() => {
				this.view_state.query = $(event.currentTarget).val();
				this.render_ledger_table();
			}, 250);
		});
		this.$ledger.on("change", ".sp-ledger-side", (event) => {
			this.view_state.side = $(event.currentTarget).val();
			this.render_ledger_table();
		});
		this.$ledger.on("click", ".sp-clear-view", () => {
			Object.assign(this.view_state, { query: "", side: "", sort_key: null, sort_dir: null });
			this.$ledger.find(".sp-ledger-search").val("");
			this.$ledger.find(".sp-ledger-side").val("");
			this.render_ledger_table();
		});
		this.$ledger.on("click", ".sp-page-prev", () => this.load_ledger_page(this.page_index - 1));
		this.$ledger.on("click", ".sp-page-next", () => this.load_ledger_page(this.page_index + 1));
	}

	ensure_desk_sidebar() {
		const title = "SmartProcess Accounting";
		const boot = (frappe.boot && frappe.boot.workspace_sidebar_item) || {};
		const data = boot[title.toLowerCase()];
		if (data && Array.isArray(data.items)) {
			const exists = data.items.some((item) => item.link_to === PAE_ROUTE);
			if (!exists) {
				data.items.push({
					label: __("گردش و مانده طرف حساب"),
					type: "Link",
					link_type: "Page",
					link_to: PAE_ROUTE,
					icon: "list",
				});
			}
		}
		if (frappe.app && frappe.app.sidebar && typeof frappe.app.sidebar.setup === "function") {
			frappe.app.sidebar.setup(title);
		}
	}

	load_defaults() {
		const company = this.company.get_value();
		if (!company) {
			return Promise.resolve();
		}
		return frappe
			.xcall(PAE_API + "overview.get_report_defaults", { company })
			.then((defaults) => {
				this.defaults = defaults;
				this.currency.df.options = [""].concat(defaults.currencies || []);
				this.currency.refresh();
				if (defaults.warning) {
					frappe.show_alert({ message: defaults.warning, indicator: "orange" });
				}
				return this.set_period(defaults.from_date, defaults.to_date || frappe.datetime.get_today());
			});
	}

	set_period(from_date, to_date) {
		this.muted = true;
		return Promise.all([this.from_date.set_value(from_date || ""), this.to_date.set_value(to_date || "")]).finally(() => {
			setTimeout(() => (this.muted = false), 50);
		});
	}

	// ---- routing ----

	show_route() {
		return this.ready.then(() => this.render_route());
	}

	render_route() {
		const route = frappe.get_route();
		if (route[0] !== PAE_ROUTE) {
			return;
		}
		if (route[1] === "ledger") {
			const state = this.route_state();
			if (state.party && state.account && state.company && state.party_type) {
				this.show_ledger(state);
				return;
			}
		}
		this.show_overview();
	}

	// Ledger state lives in path segments: this router drops query strings on push.
	route_state() {
		const segments = frappe.get_route().slice(2);
		const state = {};
		PAE_LEDGER_KEYS.forEach((key, index) => {
			const value = segments[index];
			state[key] = value && value !== PAE_EMPTY ? value : null;
		});
		return state;
	}

	set_ledger_route(state) {
		frappe.set_route(PAE_ROUTE, "ledger", ...PAE_LEDGER_KEYS.map((key) => state[key] || PAE_EMPTY));
	}

	set_mode(mode) {
		this.mode = mode;
		const overview_only = ["company", "party_type", "party", "account", "currency", "hide_zero"];
		overview_only.forEach((name) => this[name].$wrapper.toggle(mode === "overview"));
		this.show_items.$wrapper.toggle(mode === "ledger");
		this.$overview.toggle(mode === "overview");
		this.$ledger.toggle(mode === "ledger");
		this.page.set_title(mode === "ledger" ? __("گردش حساب طرف حساب") : __("گردش و مانده طرف حساب"));
		if (mode === "ledger") {
			this.page.set_secondary_action(__("بازگشت به مانده‌ها"), () => this.back_to_overview());
		} else {
			this.page.clear_secondary_action();
		}
	}

	refresh() {
		if (this.mode === "ledger") {
			this.load_ledger_page(this.page_index, true);
		} else {
			this.refresh_overview(this.overview_page);
		}
	}

	on_period_change() {
		if (this.muted) {
			return;
		}
		if (this.mode === "ledger" && this.ledger_state) {
			this.set_ledger_route({
				...this.ledger_state,
				from_date: this.from_date.get_value(),
				to_date: this.to_date.get_value(),
			});
		} else if (this.mode === "overview") {
			this.refresh_overview(1);
		}
	}

	// ---- page 1: balances ----

	show_overview() {
		this.set_mode("overview");
		if (this.ledger_dates) {
			this.set_period(this.ledger_dates.from_date, this.ledger_dates.to_date);
			this.ledger_dates = null;
		}
		if (!this.overview) {
			this.refresh_overview(1);
		}
	}

	overview_filters() {
		return {
			company: this.company.get_value(),
			party_type: this.party_type.get_value(),
			from_date: this.from_date.get_value() || null,
			to_date: this.to_date.get_value() || null,
			party: (this.party.get_value() || "").trim() || null,
			account: this.account.get_value() || null,
			currency: this.currency.get_value() || null,
			hide_zero: this.hide_zero.get_value() ? 1 : 0,
		};
	}

	refresh_overview(page) {
		const filters = this.overview_filters();
		if (!filters.company || !filters.party_type) {
			return;
		}
		this.overview_page = Math.max(cint(page), 1);
		frappe
			.xcall(PAE_API + "overview.get_balance_overview", { ...filters, page: this.overview_page, page_length: PAE_PAGE_LENGTH })
			.then((data) => {
				this.overview = data;
				this.render_overview();
			});
	}

	render_overview() {
		const data = this.overview;
		const company_currency = data.company_currency;
		const show_base = data.rows.some((row) => row.currency !== company_currency);
		const columns = pae_ledger_view.overview_columns(show_base, company_currency);
		const cell = (key, row) => {
			switch (key) {
				case "party":
					return `<td><div class="sp-party-name">${pae_format.text(row.party_name)}</div><div class="sp-party-id">${pae_format.text(row.party)}</div></td>`;
				case "account":
					return `<td>${pae_format.text(row.account)}</td>`;
				case "currency":
					return `<td>${pae_ledger_view.currency_cell(row.currency, row.other_currency_rows)}</td>`;
				case "opening":
				case "closing":
					return `<td class="${key === "closing" ? "sp-strong" : ""}">${pae_format.amount(row[key], row.currency, true)}</td>`;
				case "period_debit":
				case "period_credit":
					return `<td>${pae_format.amount(row[key], row.currency)}</td>`;
				case "nature":
					return `<td>${pae_format.text(row.nature)}</td>`;
				case "closing_base":
					return `<td class="text-muted">${pae_format.amount(row.closing_base, company_currency, true)}</td>`;
				default:
					return "<td></td>";
			}
		};
		const rows = data.rows
			.map((row, index) => `<tr class="sp-row-link" data-index="${index}" title="${__("نمایش گردش حساب")}">${columns.map((column) => cell(column.key, row)).join("")}</tr>`)
			.join("");
		const totals = (data.totals || [])
			.map(
				(total) => `<tr class="sp-total-row">
					<td colspan="2">${__("جمع")} (${total.row_count} ${__("ردیف")})</td>
					<td>${pae_format.text(total.currency)}</td>
					<td>${pae_format.amount(total.opening, total.currency, true)}</td>
					<td>${pae_format.amount(total.period_debit, total.currency)}</td>
					<td>${pae_format.amount(total.period_credit, total.currency)}</td>
					<td>${pae_format.amount(total.closing, total.currency, true)}</td>
					<td>${pae_format.text(total.nature)}</td>
					${show_base ? `<td>${pae_format.amount(total.closing_base, company_currency, true)}</td>` : ""}
				</tr>`
			)
			.join("");
		const period = `${pae_format.date(data.from_date) || "—"} ${__("تا")} ${pae_format.date(data.to_date)}`;
		this.$overview.html(`
			<div class="sp-ledger-meta"><span>${__("دوره")}: ${period}</span></div>
			<div class="sp-table-wrap">
				<table class="table sp-table sp-overview-table">
					${pae_ledger_view.colgroup(columns, this.prefs, "overview")}
					<thead><tr>${pae_ledger_view.head(columns)}</tr></thead>
					<tbody>${rows || `<tr><td colspan="${columns.length}" class="text-muted text-center">${__("ردیفی یافت نشد.")}</td></tr>`}</tbody>
					<tfoot>${totals}</tfoot>
				</table>
			</div>
			${this.pager_html(data.page > 1, data.has_more, data.page)}
			<p class="text-muted small">${__("برای دیدن گردش، روی ردیف طرف حساب کلیک کنید. ارز هر ردیف، ارز خود حساب است و هیچ ردیفی به خاطر ارز حذف نمی‌شود.")}</p>
		`);
		this.prefs.attach(this.$overview.find("table.sp-overview-table"), "overview");
	}

	pager_html(has_previous, has_next, page_number) {
		if (!has_previous && !has_next) {
			return "";
		}
		return `<div class="sp-pager">
			<button class="btn btn-default btn-xs sp-page-prev" ${has_previous ? "" : "disabled"}>${__("صفحه قبل")}</button>
			<span class="text-muted">${__("صفحه {0}", [page_number])}</span>
			<button class="btn btn-default btn-xs sp-page-next" ${has_next ? "" : "disabled"}>${__("صفحه بعد")}</button>
		</div>`;
	}

	open_ledger(row) {
		const filters = this.overview_filters();
		this.opened_from_overview = true;
		this.ledger_dates = { from_date: filters.from_date, to_date: filters.to_date };
		this.set_ledger_route({
			company: filters.company,
			party_type: filters.party_type,
			party: row.party,
			account: row.account,
			from_date: filters.from_date,
			to_date: filters.to_date,
		});
	}

	back_to_overview() {
		if (this.opened_from_overview) {
			this.opened_from_overview = false;
			window.history.back();
		} else {
			frappe.set_route(PAE_ROUTE);
		}
	}

	// ---- page 2: ledger ----

	show_ledger(state) {
		this.set_mode("ledger");
		this.ledger_state = state;
		this.set_period(state.from_date, state.to_date);
		const key = JSON.stringify(state);
		if (key === this.ledger_key) {
			return;
		}
		this.ledger_key = key;
		this.cursors = [null];
		this.reset_ledger_view();
		this.load_ledger_page(0);
	}

	load_ledger_page(index, reload) {
		if (index < 0 || index >= this.cursors.length) {
			return;
		}
		if (reload) {
			this.cursors = this.cursors.slice(0, index + 1);
			this.details.clear();
		}
		const state = this.ledger_state;
		frappe
			.xcall(PAE_API + "ledger.get_account_ledger", {
				...state,
				from_date: state.from_date || null,
				to_date: state.to_date || null,
				after: this.cursors[index],
				page_length: PAE_PAGE_LENGTH,
			})
			.then((data) => {
				this.page_index = index;
				this.cursors = this.cursors.slice(0, index + 1);
				if (data.has_more) {
					this.cursors.push(data.next_cursor);
				}
				this.ledger = data;
				this.open_details.clear();
				this.render_ledger();
			});
	}

	render_ledger() {
		const { context, summary } = this.ledger;
		this.columns = pae_ledger_view.columns(context);
		this.groups = pae_ledger_rows.groups(this.ledger.rows, this.page_index * PAE_PAGE_LENGTH, this.show_items.get_value());
		this.$ledger.html(`
			${pae_ledger_view.header(context, summary)}
			${pae_ledger_view.toolbar(this.view_state)}
			<div class="sp-table-wrap sp-ledger-wrap"></div>
			${this.pager_html(this.page_index > 0, this.ledger.has_more, this.page_index + 1)}
			<p class="text-muted small">${__("هر فاکتور با اقلام و تعدیلاتش در چند ردیف آمده است؛ جمع آن‌ها دقیقاً برابر ردیف دفتر کل همان فاکتور است.")}</p>
		`);
		this.render_ledger_table();
	}

	render_ledger_table() {
		const data = this.ledger;
		const context = data.context;
		const columns = this.columns;
		const shown = pae_ledger_rows.view(this.groups, this.view_state);
		const rows = [
			pae_ledger_view.balance_row("sp-opening-row", columns, context, {
				label: this.page_index ? __("نقل از صفحه قبل") : __("مانده اول دوره"),
				date: this.page_index ? null : context.from_date,
				balance: data.opening,
				nature: data.opening_nature,
				balance_base: data.opening_base,
			}),
		];
		shown.forEach((group) => {
			const open = this.open_details.has(group.gl_entry);
			rows.push(pae_ledger_view.group_rows(group, columns, context, open));
			if (open) {
				rows.push(pae_ledger_view.detail_row(group.gl_entry, columns, this.detail_html(group.gl_entry)));
			}
		});
		if (!shown.length) {
			rows.push(`<tr><td colspan="${columns.length}" class="text-muted text-center">${__("ردیفی یافت نشد.")}</td></tr>`);
		}
		const footer = pae_ledger_view.balance_row("sp-total-row", columns, context, {
			label: __("جمع گردش کل دوره"),
			debit: data.summary.period_debit,
			credit: data.summary.period_credit,
			balance: data.summary.closing,
			nature: data.summary.nature,
			balance_base: data.summary.closing_base,
		});
		const $wrap = this.$ledger.find(".sp-ledger-wrap");
		$wrap.html(`<table class="table sp-table sp-ledger-table">
			${pae_ledger_view.colgroup(columns, this.prefs, "ledger")}
			<thead><tr>${pae_ledger_view.head(columns, this.view_state)}</tr></thead>
			<tbody>${rows.join("")}</tbody>
			<tfoot>${footer}</tfoot>
		</table>`);
		this.prefs.attach($wrap.find("table"), "ledger");
		this.fit_detail_panels();
		this.$ledger.find(".sp-ledger-status").html(pae_ledger_view.status(this.view_state, shown.length, this.groups.length));
	}

	// ---- inline document details ----

	toggle_detail(gl_entry) {
		if (this.open_details.has(gl_entry)) {
			this.open_details.delete(gl_entry);
		} else {
			this.open_details.add(gl_entry);
			if (!this.details.has(gl_entry)) {
				this.load_detail(gl_entry);
			}
		}
		this.render_ledger_table();
	}

	load_detail(gl_entry) {
		const state = this.ledger_state;
		this.details.set(gl_entry, null);
		frappe
			.xcall(PAE_API + "document_details.get_document_detail", {
				gl_entry,
				company: state.company,
				party_type: state.party_type,
				party: state.party,
				account: state.account,
			})
			.then((detail) => this.details.set(gl_entry, detail))
			.catch(() => this.details.set(gl_entry, false))
			.finally(() => {
				if (this.open_details.has(gl_entry)) {
					this.$ledger.find("tr.sp-detail-row").filter((_index, row) => row.getAttribute("data-gl") === gl_entry).find(".sp-detail-panel").html(this.detail_html(gl_entry));
				}
			});
	}

	detail_html(gl_entry) {
		const detail = this.details.get(gl_entry);
		if (detail === false) {
			return pae_detail_view.failed();
		}
		return detail ? pae_detail_view.html(detail) : pae_detail_view.loading();
	}

	// The panel spans the whole table; keep it as wide as the visible area.
	fit_detail_panels() {
		const width = this.$ledger.find(".sp-ledger-wrap").innerWidth();
		if (width) {
			this.$ledger.find(".sp-detail-panel").css("width", `${width - 24}px`);
		}
	}

	// ---- export ----

	export_file(file_type) {
		if (this.mode === "ledger" && this.ledger_state) {
			open_url_post(frappe.request.url, {
				cmd: PAE_API + "excel_export.export_account_ledger",
				file_type,
				...this.ledger_state,
				show_items: this.show_items.get_value() ? 1 : 0,
			});
			return;
		}
		const filters = this.overview_filters();
		Object.keys(filters).forEach((key) => filters[key] === null && delete filters[key]);
		open_url_post(frappe.request.url, { cmd: PAE_API + "excel_export.export_balance_overview", file_type, ...filters });
	}
}
