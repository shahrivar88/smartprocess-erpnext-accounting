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
		this.ready = this.load_defaults();
		this.show_route();
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
			label: __("ارز"),
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
		this.$ledger.on("click", ".sp-back", () => this.back_to_overview());
		this.$ledger.on("click", ".sp-detail-btn", (event) => {
			const $row = $(event.currentTarget).closest("tr");
			this.$ledger.find("tr.sp-row-active").removeClass("sp-row-active");
			$row.addClass("sp-row-active");
			this.show_detail($row.attr("data-gl"));
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
		const rows = data.rows
			.map((row, index) => {
				const cells = [
					`<td><div class="sp-party-name">${pae_format.text(row.party_name)}</div><div class="sp-party-id">${pae_format.text(row.party)}</div></td>`,
					`<td>${pae_format.text(row.account)}</td>`,
					`<td>${pae_format.text(row.currency)}</td>`,
					`<td>${pae_format.amount(row.opening, row.currency, true)}</td>`,
					`<td>${pae_format.amount(row.period_debit, row.currency)}</td>`,
					`<td>${pae_format.amount(row.period_credit, row.currency)}</td>`,
					`<td class="sp-strong">${pae_format.amount(row.closing, row.currency, true)}</td>`,
					`<td>${pae_format.text(row.nature)}</td>`,
				];
				if (show_base) {
					cells.push(`<td class="text-muted">${pae_format.amount(row.closing_base, company_currency, true)}</td>`);
				}
				return `<tr class="sp-row-link" data-index="${index}" title="${__("نمایش گردش حساب")}">${cells.join("")}</tr>`;
			})
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
		const headers = [
			__("طرف حساب"),
			__("حساب"),
			__("ارز"),
			__("مانده اول دوره"),
			__("گردش بدهکار"),
			__("گردش بستانکار"),
			__("مانده پایان دوره"),
			__("ماهیت"),
		];
		if (show_base) {
			headers.push(__("مانده پایان دوره ({0})", [company_currency]));
		}
		const period = `${pae_format.date(data.from_date) || "—"} ${__("تا")} ${pae_format.date(data.to_date)}`;
		this.$overview.html(`
			<div class="sp-ledger-meta"><span>${__("دوره")}: ${period}</span></div>
			<div class="sp-table-wrap">
				<table class="table table-bordered sp-table">
					<thead><tr>${headers.map((label) => `<th>${label}</th>`).join("")}</tr></thead>
					<tbody>${rows || `<tr><td colspan="${headers.length}" class="text-muted text-center">${__("ردیفی یافت نشد.")}</td></tr>`}</tbody>
					<tfoot>${totals}</tfoot>
				</table>
			</div>
			${this.pager_html(data.page > 1, data.has_more, data.page)}
			<p class="text-muted small">${__("برای دیدن گردش، روی ردیف طرف حساب کلیک کنید. جمع‌ها مستقل از صفحه و فقط برای همان ارز است.")}</p>
		`);
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
				this.render_ledger();
			});
	}

	render_ledger() {
		const { context, summary } = this.ledger;
		const currency = context.currency;
		const base = context.company_currency;
		const foreign = context.is_foreign;
		const period = `${pae_format.date(context.from_date) || "—"} ${__("تا")} ${pae_format.date(context.to_date)}`;
		const card = (label, value) => `<div class="sp-ledger-total"><div class="text-muted small">${label}</div><div class="sp-strong">${value}</div></div>`;
		const base_line = foreign
			? `<div class="text-muted small sp-base-line">${__("معادل {0}", [base])}: ${__("اول دوره")} ${pae_format.amount(summary.opening_base, base, true)} · ${__("بدهکار")} ${pae_format.amount(summary.period_debit_base, base, true)} · ${__("بستانکار")} ${pae_format.amount(summary.period_credit_base, base, true)} · ${__("پایان دوره")} ${pae_format.amount(summary.closing_base, base, true)}</div>`
			: "";
		this.$ledger.html(`
			<div class="sp-ledger-summary">
				<div class="sp-ledger-head">
					<button class="btn btn-default btn-sm sp-back">${__("بازگشت به مانده‌ها")}</button>
					<div class="sp-ledger-meta">
						<span>${__("طرف حساب")}: <b>${pae_format.text(context.party_name)}</b> <span class="sp-party-id">${pae_format.text(context.party)}</span></span>
						<span>${__("حساب")}: <b>${pae_format.text(context.account)}</b></span>
						<span>${__("ارز")}: <b>${pae_format.text(currency)}</b></span>
						<span>${__("دوره")}: ${period}</span>
					</div>
				</div>
				<div class="sp-ledger-totals">
					${card(__("مانده اول دوره"), pae_format.amount(summary.opening, currency, true))}
					${card(__("گردش بدهکار"), pae_format.amount(summary.period_debit, currency, true))}
					${card(__("گردش بستانکار"), pae_format.amount(summary.period_credit, currency, true))}
					${card(__("مانده پایان دوره"), pae_format.amount(summary.closing, currency, true))}
					${card(__("ماهیت"), pae_format.text(summary.nature))}
				</div>
				${base_line}
			</div>
			<div class="sp-table-wrap">${this.ledger_table_html()}</div>
			${this.pager_html(this.page_index > 0, this.ledger.has_more, this.page_index + 1)}
			<p class="text-muted small">${__("مبلغ هر فاکتور روی ردیف‌های اقلام و تعدیلات آن آمده است؛ جمع آن‌ها دقیقاً برابر ردیف دفتر کل همان فاکتور است.")}</p>
		`);
	}

	ledger_table_html() {
		const data = this.ledger;
		const currency = data.context.currency;
		const base = data.context.company_currency;
		const foreign = data.context.is_foreign;
		const headers = [
			"#",
			__("تاریخ"),
			__("نوع سند"),
			__("شماره سند"),
			__("شرح"),
			__("عنوان قلم"),
			__("مقدار"),
			__("فی"),
			__("بدهکار"),
			__("بستانکار"),
		];
		if (foreign) {
			headers.push(__("نرخ ثبت"));
		}
		headers.push(__("مانده در خط"), __("تشخیص"), __("ردیف سند"));
		if (foreign) {
			headers.push(__("مانده {0}", [base]));
		}
		headers.push("");
		const balance_cells = (balance, nature, balance_base) => {
			const cells = [`<td class="sp-strong">${pae_format.amount(balance, currency, true)}</td>`, `<td>${pae_format.text(nature)}</td>`, "<td></td>"];
			if (foreign) {
				cells.push(`<td class="text-muted">${pae_format.amount(balance_base, base, true)}</td>`);
			}
			return cells.join("");
		};
		const lead = (label) => `<td></td><td></td><td></td><td></td><td colspan="${foreign ? 7 : 6}" class="sp-strong">${label}</td>`;
		const opening_label = this.page_index ? __("نقل از صفحه قبل") : __("مانده اول دوره");
		const rows = [`<tr class="sp-opening-row">${lead(opening_label)}${balance_cells(data.opening, data.opening_nature, data.opening_base)}<td></td></tr>`];
		const offset = this.page_index * PAE_PAGE_LENGTH;
		const split = this.show_items.get_value();
		data.rows.forEach((line, index) => {
			// A split invoice line is a header: its amounts live on its component rows.
			const components = split ? line.components || [] : [];
			const header = components.length > 0;
			const number = line.document
				? pae_format.link(line.document.doctype, line.document.name, line.document_number)
				: pae_format.text(line.document_number);
			const cells = [
				`<td class="text-muted">${offset + index + 1}</td>`,
				`<td>${pae_format.date(line.posting_date)}</td>`,
				`<td>${pae_format.text(line.voucher_label)}</td>`,
				`<td>${number}</td>`,
				`<td class="sp-remarks">${pae_format.text(line.remarks)}</td>`,
				"<td></td><td></td><td></td>",
				`<td>${header ? "" : pae_format.amount(line.debit, currency)}</td>`,
				`<td>${header ? "" : pae_format.amount(line.credit, currency)}</td>`,
			];
			if (foreign) {
				cells.push(`<td>${pae_format.rate(line.rate)}</td>`);
			}
			cells.push(`<td class="sp-strong">${header ? "" : pae_format.amount(line.balance, currency, true)}</td>`);
			cells.push(`<td>${header ? "" : pae_format.text(line.nature)}</td>`);
			cells.push(`<td class="small">${pae_format.text(line.detail_ref)}</td>`);
			if (foreign) {
				cells.push(`<td class="text-muted">${header ? "" : pae_format.amount(line.balance_base, base, true)}</td>`);
			}
			cells.push(`<td><button class="btn btn-default btn-xs sp-detail-btn">${__("جزئیات")}</button></td>`);
			rows.push(`<tr class="sp-gl-row${header ? " sp-group-row" : ""}" data-gl="${pae_format.text(line.gl_entry)}">${cells.join("")}</tr>`);
			components.forEach((entry) => rows.push(this.component_row_html(entry, currency, base, foreign)));
		});
		const total_cells = [`<td>${pae_format.amount(data.summary.period_debit, currency, true)}</td>`, `<td>${pae_format.amount(data.summary.period_credit, currency, true)}</td>`];
		if (foreign) {
			total_cells.push("<td></td>");
		}
		const footer = `<tr class="sp-total-row"><td colspan="8" class="sp-strong">${__("جمع گردش کل دوره")}</td>${total_cells.join("")}${balance_cells(data.summary.closing, data.summary.nature, data.summary.closing_base)}<td></td></tr>`;
		return `<table class="table table-bordered sp-table sp-ledger-table">
			<thead><tr>${headers.map((label) => `<th>${label}</th>`).join("")}</tr></thead>
			<tbody>${rows.join("")}</tbody>
			<tfoot>${footer}</tfoot>
		</table>`;
	}

	component_row_html(entry, currency, base, foreign) {
		const cells = [
			"<td></td><td></td><td></td><td></td>",
			`<td class="sp-remarks">${pae_format.text(entry.description)}</td>`,
			`<td class="sp-component-title">${pae_format.text(entry.title)}</td>`,
			`<td>${pae_format.number(entry.qty)}</td>`,
			`<td>${pae_format.amount(entry.rate, currency)}</td>`,
			`<td>${pae_format.amount(entry.debit, currency)}</td>`,
			`<td>${pae_format.amount(entry.credit, currency)}</td>`,
		];
		if (foreign) {
			cells.push("<td></td>");
		}
		cells.push(`<td class="sp-strong">${pae_format.amount(entry.balance, currency, true)}</td>`);
		cells.push(`<td>${pae_format.text(entry.nature)}</td>`, "<td></td>");
		if (foreign) {
			cells.push(`<td class="text-muted">${pae_format.amount(entry.balance_base, base, true)}</td>`);
		}
		cells.push("<td></td>");
		return `<tr class="sp-component-row sp-component-${pae_format.text(entry.kind)}">${cells.join("")}</tr>`;
	}

	// ---- drill-down ----

	show_detail(gl_entry) {
		const state = this.ledger_state;
		frappe
			.xcall(PAE_API + "document_details.get_document_detail", {
				gl_entry,
				company: state.company,
				party_type: state.party_type,
				party: state.party,
				account: state.account,
			})
			.then((detail) => this.open_detail_dialog(detail));
	}

	open_detail_dialog(detail) {
		const dialog = new frappe.ui.Dialog({
			title: `${detail.title || __("جزئیات سند")}${detail.document ? " — " + detail.document.name : ""}`,
			size: "extra-large",
			fields: [{ fieldtype: "HTML", fieldname: "body" }],
			primary_action_label: detail.document ? __("باز کردن سند") : null,
			primary_action: detail.document
				? () => {
						dialog.hide();
						frappe.set_route("Form", detail.document.doctype, detail.document.name);
				  }
				: null,
		});
		const body = [
			this.items_html(detail.summary),
			detail.focus && detail.focus.length ? `<h6 class="sp-detail-title">${__("ردیف انتخاب‌شده")}</h6>${this.items_html(detail.focus, "sp-focus")}` : "",
			...(detail.sections || []).map((section) => this.section_html(section)),
			this.related_html(detail.related),
			detail.technical && detail.technical.length
				? `<details class="sp-technical"><summary>${__("اطلاعات فنی")}</summary>${this.items_html(detail.technical)}</details>`
				: "",
		];
		const $body = $(`<div class="sp-party-explorer sp-detail">${body.join("")}</div>`);
		$body.on("click", "a.sp-doc-link", (event) => {
			if (event.ctrlKey || event.metaKey || event.shiftKey) {
				return;
			}
			event.preventDefault();
			dialog.hide();
			const $link = $(event.currentTarget);
			frappe.set_route("Form", $link.attr("data-doctype"), $link.attr("data-name"));
		});
		dialog.fields_dict.body.$wrapper.empty().append($body);
		dialog.show();
	}

	value_html(entry) {
		switch (entry.kind) {
			case "amount":
				return pae_format.amount(entry.value, entry.currency, true) + (entry.currency ? ` <span class="text-muted">${pae_format.text(entry.currency)}</span>` : "");
			case "rate":
				return pae_format.rate(entry.value);
			case "number":
				return pae_format.number(entry.value);
			case "date":
				return pae_format.date(entry.value);
			case "link":
				return pae_format.link(entry.doctype, entry.value);
			default:
				return pae_format.text(entry.value);
		}
	}

	items_html(items, extra_class) {
		if (!items || !items.length) {
			return "";
		}
		return `<div class="sp-detail-grid ${extra_class || ""}">${items
			.map((entry) => `<div class="sp-detail-item"><div class="text-muted small">${pae_format.text(entry.label)}</div><div>${this.value_html(entry)}</div></div>`)
			.join("")}</div>`;
	}

	section_html(section) {
		const head = section.columns.map((column) => `<th>${pae_format.text(column.label)}</th>`).join("");
		const rows = section.rows
			.map((row) => {
				const cells = section.columns
					.map((column) => {
						const entry = { kind: column.kind, value: row[column.key], doctype: row[`${column.key}_doctype`] };
						return `<td>${this.value_html(entry)}</td>`;
					})
					.join("");
				return `<tr class="${row.is_current ? "sp-row-current" : ""}">${cells}</tr>`;
			})
			.join("");
		return `<h6 class="sp-detail-title">${pae_format.text(section.title)}</h6>
			<div class="sp-table-wrap"><table class="table table-bordered sp-table"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>
			${section.note ? `<p class="text-muted small">${pae_format.text(section.note)}</p>` : ""}`;
	}

	related_html(related) {
		if (!related || !related.length) {
			return "";
		}
		return `<h6 class="sp-detail-title">${__("اسناد مرتبط")}</h6><ul class="sp-related">${related
			.map((entry) => `<li>${pae_format.text(entry.relation)}: ${pae_format.link(entry.doctype, entry.name)} <span class="text-muted small">(${pae_format.text(entry.label)})</span></li>`)
			.join("")}</ul>`;
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
