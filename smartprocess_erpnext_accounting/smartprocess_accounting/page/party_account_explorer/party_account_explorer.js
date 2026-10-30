{% include "smartprocess_erpnext_accounting/smartprocess_accounting/page/party_account_explorer/explorer/format.js" %}
{% include "smartprocess_erpnext_accounting/smartprocess_accounting/page/party_account_explorer/explorer/ledger_rows.js" %}
{% include "smartprocess_erpnext_accounting/smartprocess_accounting/page/party_account_explorer/explorer/column_prefs.js" %}
{% include "smartprocess_erpnext_accounting/smartprocess_accounting/page/party_account_explorer/explorer/ledger_view.js" %}
{% include "smartprocess_erpnext_accounting/smartprocess_accounting/page/party_account_explorer/explorer/detail_view.js" %}

const PAE_API = "smartprocess_erpnext_accounting.smartprocess_accounting.party_account.";
const PAE_ROUTE = "party-account-explorer";
const PAE_TITLE = "گردش حساب";
// The account-ledger kind: every GL row of one Account, no party.
const PAE_ACCOUNT = "Account";
// Frappe Select drops a blank value, so "all kinds" must be a real option.
const PAE_ALL = "__all__";
const PAE_LEDGER_KEYS = ["company", "party_type", "party", "currency", "account", "from_date", "to_date"];
const PAE_PAGE_LENGTH = 100;
const PAE_EMPTY = "-";
// The dates a user picked, kept for this browser tab only (survives a page refresh).
const PAE_PERIOD_KEY = "pae_period";

frappe.pages[PAE_ROUTE].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __(PAE_TITLE),
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
		this.overview_key = null;
		this.overview_sort = null;
		this.ledger = null;
		this.ledger_key = null;
		this.cursors = [null];
		this.page_index = 0;
		this.opened_from_overview = false;
		this.dates_touched = false;
		this.ledger_types = [];
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
		this.ready = Promise.all([this.restore_period(), this.load_defaults(), this.prefs.load()]);
		this.show_route();
	}

	reset_ledger_view() {
		this.filters = { search: "", side: "" };
		this.ledger_sort = null;
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
			label: __("نوع طرف حساب / حساب"),
			fieldtype: "Select",
			options: [
				{ value: PAE_ALL, label: __("همه انواع") },
				{ value: "Customer", label: __("مشتری") },
				{ value: "Supplier", label: __("تأمین‌کننده") },
			],
			default: PAE_ALL,
			change: overview_change,
		});
		this.party = this.page.add_field({
			fieldname: "party",
			label: __("جستجو (نام یا کد)"),
			fieldtype: "Data",
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
			change: () => this.on_period_change(),
		});
		this.account = this.page.add_field({
			fieldname: "account",
			label: __("حساب معین (اختیاری)"),
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
		this.hide_zero = this.page.add_field({
			fieldname: "hide_zero",
			label: __("مخفی کردن حساب‌های بدون مانده و گردش"),
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
		this.$overview.on("click", "th.sp-sortable", (event) => {
			this.overview_sort = pae_ledger_view.next_sort(this.overview_sort, $(event.currentTarget).attr("data-sort-key"));
			this.refresh_overview(1);
		});
		this.$overview.on("click", ".sp-page-prev", () => this.refresh_overview(this.overview_page - 1));
		this.$overview.on("click", ".sp-page-next", () => this.refresh_overview(this.overview_page + 1));
		this.$ledger.on("click", "th.sp-sortable", (event) => {
			this.ledger_sort = pae_ledger_view.next_sort(this.ledger_sort, $(event.currentTarget).attr("data-sort-key"));
			this.cursors = [null];
			this.load_ledger_page(0);
		});
		this.$ledger.on("click", ".sp-detail-btn", (event) => this.show_detail($(event.currentTarget).closest("tr").attr("data-gl")));
		this.$ledger.on("input", ".sp-ledger-search", (event) => {
			clearTimeout(this.search_timer);
			const search = $(event.currentTarget).val();
			this.search_timer = setTimeout(() => this.apply_filters({ search }), 400);
		});
		this.$ledger.on("change", ".sp-ledger-side", (event) => this.apply_filters({ side: $(event.currentTarget).val() }));
		this.$ledger.on("click", ".sp-clear-view", () => this.apply_filters({ search: "", side: "" }));
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
					label: __(PAE_TITLE),
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

	// Company defaults: the fiscal year that contains the user's today, the ledger
	// kinds and currencies. Dates the user already picked are never overwritten.
	load_defaults() {
		const company = this.company.get_value();
		if (!company) {
			return Promise.resolve();
		}
		return frappe
			.xcall(PAE_API + "overview.get_report_defaults", { company, as_of: frappe.datetime.get_today() })
			.then((defaults) => {
				this.defaults = defaults;
				this.currency.df.options = [""].concat(defaults.currencies || []);
				this.currency.refresh();
				this.set_ledger_types(defaults.ledger_types || []);
				if (this.dates_touched) {
					return;
				}
				if (defaults.warning) {
					frappe.show_alert({ message: defaults.warning, indicator: "orange" });
				}
				return this.set_period(defaults.from_date, defaults.to_date || frappe.datetime.get_today());
			});
	}

	set_ledger_types(options) {
		if (!options.length) {
			return;
		}
		this.ledger_types = options;
		const current = this.as_select_value(this.party_type.get_value());
		this.party_type.df.options = options.map((option) => ({
			value: this.as_select_value(option.value),
			label: option.label,
		}));
		this.party_type.refresh();
		const values = options.map((option) => this.as_select_value(option.value));
		const has_all = values.includes(PAE_ALL);
		const value = values.includes(current) ? current : has_all ? PAE_ALL : values[0];
		this.muted = true;
		Promise.resolve(this.party_type.set_value(value)).finally(() => setTimeout(() => (this.muted = false), 50));
	}

	as_select_value(value) {
		return value ? value : PAE_ALL;
	}

	// The selected kind: every allowed type, one Party Type, or the account ledger.
	ledger_choice() {
		const value = this.party_type.get_value() || "";
		if (!value || value === PAE_ALL) {
			return { party_type: "", account_type: null };
		}
		const option = this.ledger_types.find((entry) => entry.value === value);
		if (option) {
			return { party_type: option.party_type, account_type: option.account_type || null };
		}
		const [party_type, account_type] = value.split(":");
		return { party_type, account_type: account_type || null };
	}

	set_period(from_date, to_date) {
		this.muted = true;
		return Promise.all([this.from_date.set_value(from_date || ""), this.to_date.set_value(to_date || "")]).finally(() => {
			setTimeout(() => (this.muted = false), 50);
		});
	}

	restore_period() {
		let stored = null;
		try {
			stored = JSON.parse(window.sessionStorage.getItem(PAE_PERIOD_KEY) || "null");
		} catch (error) {
			stored = null;
		}
		if (!stored || !(stored.from_date || stored.to_date)) {
			return Promise.resolve();
		}
		this.dates_touched = true;
		return this.set_period(stored.from_date, stored.to_date);
	}

	remember_period() {
		this.dates_touched = true;
		try {
			window.sessionStorage.setItem(
				PAE_PERIOD_KEY,
				JSON.stringify({ from_date: this.from_date.get_value() || null, to_date: this.to_date.get_value() || null })
			);
		} catch (error) {
			// Storage can be unavailable (private mode); the dates still apply to this view.
		}
	}

	// ---- routing ----

	show_route() {
		return this.ready.then(() => this.apply_route_options()).then(() => this.render_route());
	}

	apply_route_options() {
		const options = frappe.route_options;
		if (!options || typeof options !== "object") {
			return Promise.resolve();
		}
		frappe.route_options = null;
		this.muted = true;
		const jobs = [];
		if (options.company) {
			jobs.push(this.company.set_value(options.company));
		}
		if ("party_type" in options) {
			jobs.push(this.party_type.set_value(this.as_select_value(options.party_type)));
		}
		if ("party" in options) {
			jobs.push(this.party.set_value(options.party || ""));
		}
		if (options.account) {
			jobs.push(this.account.set_value(options.account));
		}
		if (options.currency) {
			jobs.push(this.currency.set_value(options.currency));
		}
		if ("hide_zero" in options) {
			jobs.push(this.hide_zero.set_value(cint(options.hide_zero)));
		}
		return Promise.all(jobs).finally(() => setTimeout(() => (this.muted = false), 50));
	}

	render_route() {
		const route = frappe.get_route();
		if (route[0] !== PAE_ROUTE) {
			return;
		}
		if (route[1] === "ledger") {
			const state = this.route_state();
			const target = state.party_type === PAE_ACCOUNT ? state.account : state.party && (state.currency || state.account);
			if (target && state.company && state.party_type) {
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
		this.page.set_title(__(PAE_TITLE));
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
		this.remember_period();
		const dates = { from_date: this.from_date.get_value(), to_date: this.to_date.get_value() };
		if (this.mode === "ledger" && this.ledger_state) {
			if (this.ledger_dates) {
				this.ledger_dates = dates;
			}
			this.set_ledger_route({ ...this.ledger_state, ...dates });
		} else if (this.mode === "overview") {
			this.refresh_overview(1);
		}
	}

	// ---- page 1: balances ----

	show_overview() {
		this.set_mode("overview");
		const dates = this.ledger_dates;
		this.ledger_dates = null;
		return Promise.resolve(dates && this.set_period(dates.from_date, dates.to_date)).then(() => {
			if (!this.overview || this.overview_key !== JSON.stringify(this.overview_filters())) {
				this.refresh_overview(1);
			}
		});
	}

	overview_filters() {
		const choice = this.ledger_choice();
		return {
			company: this.company.get_value(),
			party_type: choice.party_type,
			account_type: choice.account_type,
			from_date: this.from_date.get_value() || null,
			to_date: this.to_date.get_value() || null,
			party: (this.party.get_value() || "").trim() || null,
			account: this.account.get_value() || null,
			currency: this.currency.get_value() || null,
			hide_zero: this.hide_zero.get_value() ? 1 : 0,
		};
	}

	sort_args(sort) {
		return sort ? { sort_by: sort.key, sort_order: sort.order } : {};
	}

	refresh_overview(page) {
		const filters = this.overview_filters();
		if (!filters.company) {
			return;
		}
		this.overview_page = Math.max(cint(page), 1);
		this.overview_key = JSON.stringify(filters);
		frappe
			.xcall(PAE_API + "overview.get_balance_overview", {
				...filters,
				...this.sort_args(this.overview_sort),
				page: this.overview_page,
				page_length: PAE_PAGE_LENGTH,
			})
			.then((data) => {
				this.overview = data;
				this.render_overview();
			});
	}

	render_overview() {
		const data = this.overview;
		const company_currency = data.company_currency;
		const columns = pae_ledger_view.overview_columns(data.by_account, data.mixed);
		const cells = (row) => columns.map((column) => pae_ledger_view.overview_cell(column.key, row, company_currency)).join("");
		const rows = data.rows
			.map((row, index) => `<tr class="sp-row-link" data-index="${index}" title="${__("نمایش ریزگردش")}">${cells(row)}</tr>`)
			.join("");
		const totals = (data.totals || [])
			.map((total) => `<tr class="sp-total-row">${cells({ ...total, party_name: `${__("جمع")} (${total.row_count} ${__("ردیف")})` })}</tr>`)
			.join("");
		const period = `${pae_format.date(data.from_date) || "—"} ${__("تا")} ${pae_format.date(data.to_date)}`;
		const note = data.mixed
			? __("برای دیدن ریزگردش، روی ردیف کلیک کنید. هر ردیف یا یک طرف حساب است یا یک حساب دفتر کل که همان تراکنش طرف حساب نیست.")
			: data.by_account
				? __("برای دیدن ریزگردش، روی ردیف حساب کلیک کنید. هر ردیف همه ردیف‌های دفتر کل یک حساب است؛ ستون‌های ساده به ارز پایه و ستون‌های ارزی به ارز حساب از دفتر کل خوانده می‌شوند.")
				: __("برای دیدن ریزگردش، روی ردیف طرف حساب کلیک کنید. هر ردیف جمع حساب‌های هم‌ارز طرف حساب است؛ ستون‌های ساده به ارز پایه و ستون‌های ارزی به ارز حساب از دفتر کل خوانده می‌شوند.");
		this.$overview.html(`
			<div class="sp-ledger-meta"><span>${__("دوره")}: ${period}</span></div>
			<div class="sp-table-wrap">
				<table class="table sp-table sp-overview-table">
					${pae_ledger_view.colgroup(columns, this.prefs, "overview")}
					<thead><tr>${pae_ledger_view.head(columns, this.overview_sort)}</tr></thead>
					<tbody>${rows || `<tr><td colspan="${columns.length}" class="text-muted text-center">${__("ردیفی یافت نشد.")}</td></tr>`}</tbody>
					<tfoot>${totals}</tfoot>
				</table>
			</div>
			${this.pager_html(data.page > 1, data.has_more, data.page)}
			<p class="text-muted small">${note}</p>
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
		const by_account = row.by_account || filters.party_type === PAE_ACCOUNT;
		this.opened_from_overview = true;
		this.ledger_dates = { from_date: filters.from_date, to_date: filters.to_date };
		this.set_ledger_route({
			company: filters.company,
			party_type: by_account ? PAE_ACCOUNT : row.party_type || filters.party_type,
			party: by_account ? null : row.party,
			currency: row.currency,
			account: by_account ? row.account : filters.account,
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
		}
		const state = this.ledger_state;
		const request = (this.ledger_request || 0) + 1;
		this.ledger_request = request;
		frappe
			.xcall(PAE_API + "ledger.get_account_ledger", {
				...state,
				from_date: state.from_date || null,
				to_date: state.to_date || null,
				after: this.cursors[index],
				page_length: PAE_PAGE_LENGTH,
				search: this.filters.search.trim() || null,
				side: this.filters.side || null,
				...this.sort_args(this.ledger_sort),
			})
			.then((data) => {
				if (request !== this.ledger_request) {
					return;
				}
				this.page_index = index;
				this.cursors = this.cursors.slice(0, index + 1);
				if (data.has_more) {
					this.cursors.push(data.next_cursor);
				}
				this.ledger = data;
				this.render_ledger();
			});
	}

	// Search and debit/credit filters run on the server over the whole period.
	apply_filters(changes) {
		Object.assign(this.filters, changes);
		this.cursors = [null];
		this.load_ledger_page(0);
	}

	render_ledger() {
		const { context, summary } = this.ledger;
		const focused = document.activeElement && document.activeElement.classList.contains("sp-ledger-search");
		this.columns = pae_ledger_view.columns(context);
		this.groups = pae_ledger_rows.groups(this.ledger.rows, this.page_index * PAE_PAGE_LENGTH, this.show_items.get_value());
		this.$ledger.html(`
			${pae_ledger_view.header(context, summary)}
			${pae_ledger_view.toolbar(this.filters)}
			<div class="sp-table-wrap sp-ledger-wrap"></div>
			${this.pager_html(this.page_index > 0, this.ledger.has_more, this.page_index + 1)}
			<p class="text-muted small">${__("هر فاکتور با اقلام و تعدیلاتش در چند ردیف آمده است؛ جمع آن‌ها در هر دو ارز دقیقاً برابر ردیف دفتر کل همان فاکتور است.")}
				${__("ستون «نرخ ارز» نرخ ذخیره‌شده در همان ردیف دفتر کل است (ارز پایه به ازای یک واحد ارز حساب)؛ اگر نرخ قابل اتکایی ثبت نشده باشد «—» نمایش داده می‌شود.")}
				${__("ستون «جزئیات» حساب معین هر ردیف و سندی را که آن را ثبت کرده است نشان می‌دهد.")}</p>
		`);
		this.render_ledger_table();
		if (focused) {
			const input = this.$ledger.find(".sp-ledger-search").get(0);
			input.focus();
			input.setSelectionRange(input.value.length, input.value.length);
		}
	}

	render_ledger_table() {
		const data = this.ledger;
		const context = data.context;
		const columns = this.columns;
		const rows = [];
		// A filtered or sorted page after the first has no meaningful carry-forward row.
		const windowed = data.filtered || data.sorted;
		if (!(windowed && this.page_index > 0)) {
			rows.push(
				pae_ledger_view.balance_row("sp-opening-row", columns, context, {
					label: this.page_index ? __("نقل از صفحه قبل") : __("مانده اول دوره"),
					date: this.page_index ? null : context.from_date,
					balance: data.opening,
					balance_base: data.opening_base,
				})
			);
		}
		this.groups.forEach((group) => rows.push(pae_ledger_view.group_rows(group, columns, context)));
		if (!this.groups.length) {
			rows.push(`<tr><td colspan="${columns.length}" class="text-muted text-center">${__("ردیفی یافت نشد.")}</td></tr>`);
		}
		const footer = [];
		if (data.filter_totals) {
			footer.push(
				pae_ledger_view.balance_row("sp-total-row sp-filtered-total", columns, context, {
					label: __("جمع {0} ردیف فیلترشده", [data.filter_totals.row_count]),
					debit: data.filter_totals.debit,
					credit: data.filter_totals.credit,
					debit_base: data.filter_totals.debit_base,
					credit_base: data.filter_totals.credit_base,
				})
			);
		}
		footer.push(
			pae_ledger_view.balance_row("sp-total-row", columns, context, {
				label: __("جمع گردش کل دوره"),
				debit: data.summary.period_debit,
				credit: data.summary.period_credit,
				debit_base: data.summary.period_debit_base,
				credit_base: data.summary.period_credit_base,
				balance: data.summary.closing,
				balance_base: data.summary.closing_base,
			})
		);
		const $wrap = this.$ledger.find(".sp-ledger-wrap");
		$wrap.html(`<table class="table sp-table sp-ledger-table">
			${pae_ledger_view.colgroup(columns, this.prefs, "ledger")}
			<thead><tr>${pae_ledger_view.head(columns, this.ledger_sort)}</tr></thead>
			<tbody>${rows.join("")}</tbody>
			<tfoot>${footer.join("")}</tfoot>
		</table>`);
		this.prefs.attach($wrap.find("table"), "ledger");
		this.$ledger
			.find(".sp-ledger-status")
			.html(pae_ledger_view.status(this.filters, data.filter_totals, context.currency, context.company_currency, data.sorted));
	}

	// ---- document details dialog ----

	show_detail(gl_entry) {
		const state = this.ledger_state;
		const line = (this.ledger.rows || []).find((row) => row.gl_entry === gl_entry) || {};
		const $body = $('<div class="sp-party-explorer sp-detail"></div>').html(pae_detail_view.loading());
		const dialog = new frappe.ui.Dialog({ title: __("جزئیات سند"), size: "extra-large" });
		$body.appendTo(dialog.body);
		$body.on("click", "a.sp-doc-link", (event) => {
			if (event.ctrlKey || event.metaKey || event.shiftKey || event.button === 1) {
				return;
			}
			event.preventDefault();
			event.stopPropagation();
			dialog.hide();
			frappe.set_route("Form", $(event.currentTarget).attr("data-doctype"), $(event.currentTarget).attr("data-name"));
		});
		dialog.show();
		frappe
			.xcall(PAE_API + "document_details.get_document_detail", {
				gl_entry,
				company: state.company,
				party_type: state.party_type,
				party: state.party,
				account: line.account || state.account,
			})
			.then((detail) => {
				dialog.set_title(pae_detail_view.title(detail));
				$body.html(pae_detail_view.html(detail));
				if (detail.document) {
					dialog.set_primary_action(__("باز کردن سند کامل"), () => {
						dialog.hide();
						frappe.set_route("Form", detail.document.doctype, detail.document.name);
					});
				}
			})
			.catch(() => $body.html(pae_detail_view.failed()));
	}

	// ---- export ----

	export_file(file_type) {
		if (this.mode === "ledger" && this.ledger_state) {
			const args = {
				cmd: PAE_API + "excel_export.export_account_ledger",
				file_type,
				...this.ledger_state,
				show_items: this.show_items.get_value() ? 1 : 0,
				...this.sort_args(this.ledger_sort),
			};
			if (this.filters.search.trim()) {
				args.search = this.filters.search.trim();
			}
			if (this.filters.side) {
				args.side = this.filters.side;
			}
			Object.keys(args).forEach((key) => (args[key] === null || args[key] === undefined) && delete args[key]);
			open_url_post(frappe.request.url, args);
			return;
		}
		const filters = { ...this.overview_filters(), ...this.sort_args(this.overview_sort) };
		Object.keys(filters).forEach((key) => filters[key] === null && delete filters[key]);
		open_url_post(frappe.request.url, { cmd: PAE_API + "excel_export.export_balance_overview", file_type, ...filters });
	}
}
