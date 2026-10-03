frappe.pages["party-account-explorer"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("گردش و مانده طرف حساب"),
		single_column: true,
	});
	try {
		frappe.party_account_explorer = new PartyAccountExplorer(page);
	} catch (e) {
		console.error(e);
		frappe.msgprint({ message: String(e && (e.stack || e.message || e)), indicator: "red" });
	}
};

function currency_precision(currency) {
	// Same rule frappe applies to Currency fields (frappe.meta.get_field_precision):
	// the site's configured currency precision, otherwise the currency's own number
	// format — no currency code is hard-coded in the display logic.
	const configured = cint(frappe.defaults.get_default("currency_precision"));
	if (configured) {
		return configured;
	}
	return get_number_format_info(get_number_format(currency)).precision;
}

class PartyAccountExplorer {
	constructor(page) {
		this.page = page;
		this.mode = "overview";
		this.transactions = [];
		this.lines = [];
		this.balances = [];
		this.ledger_context = null;
		this.settings_key = "party-account-explorer";
		this.column_settings = this.read_local_column_settings();
		try {
			const saved =
				typeof frappe.get_user_settings === "function"
					? frappe.get_user_settings(this.settings_key, "column_settings")
					: null;
			if (saved && typeof saved === "object") {
				this.column_settings = saved;
			}
		} catch (e) {
			/* keep local */
		}
		this.current_columns = [];
		this.current_rows = [];
		this.current_kind = "overview";
		this.make_filters();
		this.make_result();
		this.page.set_primary_action(__("نمایش"), () => this.refresh());
		this.make_export_actions();
		this.ensure_desk_sidebar();
		const ready = this.load_user_settings();
		if (ready && typeof ready.finally === "function") {
			ready.finally(() => this.refresh_overview());
		} else {
			this.refresh_overview();
		}
	}

	local_settings_key() {
		return `sp-explorer-columns:${frappe.session.user || "Guest"}`;
	}

	read_local_column_settings() {
		try {
			const raw = localStorage.getItem(this.local_settings_key());
			const parsed = raw ? JSON.parse(raw) : {};
			return parsed && typeof parsed === "object" ? parsed : {};
		} catch (e) {
			return {};
		}
	}

	load_user_settings() {
		this.column_settings = this.column_settings || this.read_local_column_settings();
		try {
			if (!frappe.model.user_settings || typeof frappe.model.user_settings.get !== "function") {
				return Promise.resolve();
			}
			return frappe.model.user_settings
				.get(this.settings_key)
				.then((settings) => {
					if (settings && settings.column_settings) {
						this.column_settings = settings.column_settings;
					}
				})
				.catch(() => {});
		} catch (e) {
			return Promise.resolve();
		}
	}

	make_filters() {
		this.company = this.page.add_field({
			fieldname: "company",
			label: __("شرکت"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_default("company"),
			change: () => this.on_company_change(),
		});
		this.party_type = this.page.add_field({
			fieldname: "party_type",
			label: __("نوع طرف حساب"),
			fieldtype: "Select",
			options: "Customer\nSupplier",
			reqd: 1,
			default: "Customer",
			change: () => {
				if (this.mode === "overview") {
					this.refresh_overview();
				}
			},
		});
		this.currency = this.page.add_field({
			fieldname: "currency",
			label: __("ارز"),
			fieldtype: "Select",
			options: "",
			reqd: 1,
			change: () => {
				if (this.mode === "overview") {
					this.refresh_overview();
				}
			},
		});
		this.as_of_date = this.page.add_field({
			fieldname: "as_of_date",
			label: __("تا تاریخ"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			change: () => {
				if (this.mode === "overview") {
					this.refresh_overview();
				}
			},
		});
		this.party = this.page.add_field({
			fieldname: "party",
			label: __("جستجوی طرف حساب"),
			fieldtype: "Data",
			change: () => {
				if (this.mode === "overview") {
					this.refresh_overview();
				}
			},
		});
		this.hide_zero = this.page.add_field({
			fieldname: "hide_zero",
			label: __("مخفی کردن مانده صفر"),
			fieldtype: "Check",
			default: 1,
			change: () => {
				if (this.mode === "overview") {
					this.refresh_overview();
				}
			},
		});
		this.from_date = this.page.add_field({
			fieldname: "from_date",
			label: __("از تاریخ"),
			fieldtype: "Date",
			default: frappe.datetime.year_start(),
		});
		this.to_date = this.page.add_field({
			fieldname: "to_date",
			label: __("تا تاریخ گردش"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		});
		this.set_filter_mode("overview");
		this.load_currencies(true);
	}

	on_company_change() {
		this.load_currencies(false);
		if (this.mode === "overview") {
			this.refresh_overview();
		}
	}

	load_currencies(force_default) {
		const company = this.company.get_value();
		frappe.call({
			method:
				"smartprocess_erpnext_accounting.smartprocess_accounting.party_account.item_ledger.get_available_currencies",
			args: { company: company },
			callback: (r) => {
				const list = r.message || [];
				const previous = this.currency.get_value();
				this.currency.df.options = list.join("\n");
				this.currency.refresh();
				if (previous && list.includes(previous) && !force_default) {
					this.currency.set_value(previous);
				} else if (list.length) {
					this.currency.set_value(list[0]);
				}
			},
		});
	}

	set_filter_mode(mode) {
		this.mode = mode;
		const overview = mode === "overview";
		this.as_of_date.$wrapper.toggle(overview);
		this.hide_zero.$wrapper.toggle(overview);
		this.party.$wrapper.toggle(overview);
		this.from_date.$wrapper.toggle(!overview);
		this.to_date.$wrapper.toggle(!overview);
		if (overview) {
			this.page.clear_secondary_action();
		} else {
			this.page.set_secondary_action(__("بازگشت به مانده‌ها"), () => this.back_to_overview());
		}
		this.make_export_actions();
	}

	make_export_actions() {
		this.page.clear_menu();
		this.page.add_menu_item(__("خروجی اکسل"), () => this.export_excel());
		this.page.add_menu_item(__("خروجی PDF"), () => this.export_pdf());
		this.page.show_menu();
		if (this.page.menu_btn_group) {
			this.page.menu_btn_group.removeClass("hide hidden-xl");
		}
	}

	ensure_desk_sidebar() {
		const title = "SmartProcess Accounting";
		const key = title.toLowerCase();
		const boot = (frappe.boot && frappe.boot.workspace_sidebar_item) || {};
		const data = boot[key];
		if (data && Array.isArray(data.items)) {
			const exists = data.items.some((item) => item.link_to === "party-account-explorer");
			if (!exists) {
				data.items.push({
					label: __("گردش و مانده طرف حساب"),
					type: "Link",
					link_type: "Page",
					link_to: "party-account-explorer",
					icon: "list",
				});
			}
		}
		if (frappe.app && frappe.app.sidebar && typeof frappe.app.sidebar.setup === "function") {
			frappe.app.sidebar.setup(title);
		}
	}

	make_result() {
		this.$wrap = $('<div class="sp-party-explorer"></div>').appendTo(this.page.main);
		this.$summary = $('<div class="margin-top"></div>').appendTo(this.$wrap);
		this.$table = $('<div class="margin-top"></div>').appendTo(this.$wrap);
		this.$hint = $('<p class="text-muted small"></p>').appendTo(this.$wrap);
	}

	refresh() {
		if (this.mode === "ledger") {
			this.refresh_ledger();
		} else {
			this.refresh_overview();
		}
	}

	refresh_overview() {
		if (!this.company.get_value() || !this.party_type.get_value() || !this.currency.get_value()) {
			return;
		}
		this.set_filter_mode("overview");
		frappe.call({
			method:
				"smartprocess_erpnext_accounting.smartprocess_accounting.party_account.overview.get_party_balance_overview",
			args: {
				company: this.company.get_value(),
				party_type: this.party_type.get_value(),
				currency: this.currency.get_value(),
				as_of_date: this.as_of_date.get_value(),
				party: this.party.get_value(),
				hide_zero: this.hide_zero.get_value(),
			},
			freeze: true,
			callback: (r) => this.render_overview(r.message || {}),
		});
	}

	render_overview(data) {
		this.balances = data.rows || [];
		const currency = data.currency || this.currency.get_value();
		this.$summary.html(
			`<div class="text-muted">
				${__("مانده طرف حساب")} — ${frappe.utils.escape_html(currency)}
			</div>`
		);
		this.$hint.text(__("برای مشاهده گردش، روی ردیف کلیک کنید."));
		const rows = this.balances.map((row) => [
			row.party,
			row.party_name || row.party,
			row.currency,
			row.debit,
			row.credit,
			row.balance,
			row.balance_nature,
		]);
		this.render_table(
			[
				this.key_column(),
				this.text_column("party", __("طرف حساب"), 250),
				this.text_column("currency", __("ارز"), 70),
				this.amount_column("debit", __("بدهکار"), 130, currency),
				this.amount_column("credit", __("بستانکار"), 130, currency),
				this.amount_column("balance", __("مانده"), 140, currency),
				this.text_column("nature", __("ماهیت"), 80),
			],
			rows,
			__("مانده‌ای یافت نشد."),
			"overview"
		);
	}

	open_ledger(row) {
		this.ledger_context = row;
		this.to_date.set_value(this.as_of_date.get_value() || frappe.datetime.get_today());
		this.set_filter_mode("ledger");
		this.refresh_ledger();
	}

	back_to_overview() {
		this.ledger_context = null;
		this.transactions = [];
		this.lines = [];
		this.set_filter_mode("overview");
		this.refresh_overview();
	}

	refresh_ledger() {
		const ctx = this.ledger_context;
		if (!ctx || !this.company.get_value()) {
			frappe.msgprint(__("ابتدا یک طرف حساب را از فهرست مانده انتخاب کنید."));
			return;
		}
		frappe.call({
			method:
				"smartprocess_erpnext_accounting.smartprocess_accounting.party_account.item_ledger.get_party_item_ledger",
			args: {
				company: this.company.get_value(),
				party_type: ctx.party_type || this.party_type.get_value(),
				party: ctx.party,
				from_date: this.from_date.get_value(),
				to_date: this.to_date.get_value(),
				currency: ctx.currency || this.currency.get_value(),
			},
			freeze: true,
			callback: (r) => this.render_ledger(r.message || {}),
		});
	}

	render_ledger(data) {
		this.lines = data.lines || [];
		this.transactions = this.lines;
		const account_currency = data.account_currency || "";
		const company_currency = data.company_currency || "";
		const is_foreign = !!data.is_foreign;
		const ctx = this.ledger_context || {};
		let totals = "";
		if (is_foreign) {
			totals = `
			<div class="sp-ledger-totals">
				<div class="sp-ledger-total"><b>${__("گردش بدهکار")} (${frappe.utils.escape_html(account_currency)}):</b> ${this.format_amount(data.period_debit_account, account_currency)}</div>
				<div class="sp-ledger-total"><b>${__("گردش بستانکار")} (${frappe.utils.escape_html(account_currency)}):</b> ${this.format_amount(data.period_credit_account, account_currency)}</div>
				<div class="sp-ledger-total"><b>${__("مانده پایان دوره")} (${frappe.utils.escape_html(account_currency)}):</b> ${this.format_amount(data.closing_account, account_currency)}</div>
			</div>
			<div class="sp-ledger-totals">
				<div class="sp-ledger-total"><b>${__("گردش بدهکار")} (${frappe.utils.escape_html(company_currency)}):</b> ${this.format_amount(data.period_debit_base, company_currency)}</div>
				<div class="sp-ledger-total"><b>${__("گردش بستانکار")} (${frappe.utils.escape_html(company_currency)}):</b> ${this.format_amount(data.period_credit_base, company_currency)}</div>
				<div class="sp-ledger-total"><b>${__("مانده پایان دوره")} (${frappe.utils.escape_html(company_currency)}):</b> ${this.format_amount(data.closing_base, company_currency)}</div>
			</div>`;
		} else {
			totals = `
			<div class="sp-ledger-totals">
				<div class="sp-ledger-total"><b>${__("گردش بدهکار")}:</b> ${this.format_amount(data.period_debit_base, company_currency)}</div>
				<div class="sp-ledger-total"><b>${__("گردش بستانکار")}:</b> ${this.format_amount(data.period_credit_base, company_currency)}</div>
				<div class="sp-ledger-total"><b>${__("مانده پایان دوره")}:</b> ${this.format_amount(data.closing_base, company_currency)}</div>
			</div>`;
		}
		this.$summary.html(
			`<div class="sp-ledger-summary">
				<div class="sp-ledger-meta">
					<b>${__("طرف حساب")}:</b> ${frappe.utils.escape_html(ctx.party_name || ctx.party || "")}
					<span class="sp-ledger-sep">|</span>
					<b>${__("ارز")}:</b> ${frappe.utils.escape_html(account_currency)}
					<span class="sp-ledger-sep">|</span>
					<b>${__("از تاریخ")}:</b> ${frappe.datetime.str_to_user(this.from_date.get_value())}
					<span class="sp-ledger-sep">|</span>
					<b>${__("تا تاریخ")}:</b> ${frappe.datetime.str_to_user(this.to_date.get_value())}
				</div>
				${totals}
			</div>`
		);
		this.$hint.text(__("برای باز کردن سند روی ستون عنوان کلیک کنید."));
		const rows = this.lines.map((row, idx) => this.ledger_display_row(row, idx, is_foreign, account_currency, company_currency));
		this.render_table(
			this.ledger_columns(is_foreign, account_currency, company_currency),
			rows,
			__("گردشی یافت نشد."),
			is_foreign ? "ledger_foreign" : "ledger_base"
		);
	}

	key_column() {
		return { id: "key", name: "key", width: 1, editable: false, sortable: false, dropdown: false };
	}

	text_column(id, name, width) {
		return { id, name, width, editable: false, sortable: true, dropdown: false };
	}

	amount_column(id, name, width, currency) {
		return {
			id,
			name,
			width,
			editable: false,
			sortable: true,
			dropdown: false,
			format: (value) => this.format_amount(value, currency),
		};
	}

	ledger_columns(is_foreign, account_currency, company_currency) {
		const columns = [
			this.key_column(),
			this.text_column("date", __("تاریخ"), 100),
			this.text_column("source", __("عنوان"), 260),
			this.text_column("account", __("حساب معین"), 190),
			this.text_column("description", __("شرح قلم"), 200),
			this.text_column("item_title", __("عنوان قلم"), 180),
			this.amount_column("qty", __("مقدار"), 70, account_currency),
			this.amount_column("rate", __("فی"), 90, is_foreign ? account_currency : company_currency),
		];
		if (is_foreign) {
			columns.push(
				this.amount_column("debit_account", __("بد") + " " + account_currency, 110, account_currency),
				this.amount_column("credit_account", __("بس") + " " + account_currency, 110, account_currency),
				this.amount_column("running_account", __("مانده") + " " + account_currency, 120, account_currency),
				this.amount_column("debit_base", __("بد") + " " + company_currency, 120, company_currency),
				this.amount_column("credit_base", __("بس") + " " + company_currency, 120, company_currency),
				this.amount_column("running_base", __("مانده در خط"), 130, company_currency)
			);
		} else {
			columns.push(
				this.amount_column("debit_base", __("بد"), 120, company_currency),
				this.amount_column("credit_base", __("بس"), 120, company_currency),
				this.amount_column("running_base", __("مانده در خط"), 130, company_currency)
			);
		}
		return columns;
	}

	format_source_label(row) {
		if (row.source_label) {
			return row.source_label;
		}
		const is_return = !!row.is_return;
		let kind = row.voucher_type || __("سند");
		if (row.voucher_type === "Sales Invoice") {
			kind = is_return ? __("برگشت از فروش") : __("فاکتور فروش");
		} else if (row.voucher_type === "Purchase Invoice") {
			kind = is_return ? __("برگشت از خرید") : __("فاکتور خرید");
		} else if (row.voucher_type === "Journal Entry") {
			kind = __("سند حسابداری");
		} else if (row.voucher_type === "Payment Entry") {
			kind = __("سند مالی");
		} else if (row.voucher_type === "SmartProcess Currency Conversion") {
			kind = __("تبدیل");
		}
		const number = String(row.voucher_no || "").trim();
		return number ? `${kind} ${number}` : kind;
	}

	ledger_display_row(row, idx, is_foreign, account_currency, company_currency) {
		const source = frappe.utils.escape_html(this.format_source_label(row) || row.voucher_no || "");
		const cells = [
			String(idx),
			frappe.datetime.str_to_user(row.posting_date),
			row.voucher_type && row.voucher_no
				? `<a href="#" class="sp-source-link" data-doctype="${frappe.utils.escape_html(
						row.voucher_type
				  )}" data-name="${frappe.utils.escape_html(row.voucher_no)}">${source}</a>`
				: source,
			row.account || "",
			row.description || "",
			row.title || "",
			row.qty,
			row.rate,
		];
		if (is_foreign) {
			cells.push(
				row.debit_account,
				row.credit_account,
				row.running_account,
				row.debit_base,
				row.credit_base,
				row.running_base
			);
		} else {
			cells.push(row.debit_base, row.credit_base, row.running_base);
		}
		return cells;
	}

	format_rate(value, currency) {
		if (value === null || value === undefined || value === "") {
			return "";
		}
		return this.format_amount(value, currency);
	}

	render_table(columns, rows, empty_message, kind) {
		this.current_kind = kind || this.mode;
		this.current_columns = this.apply_saved_layout(columns, this.current_kind);
		this.current_rows = rows;
		if (this.datatable) {
			this.datatable.destroy();
			this.datatable = null;
			this.$table.empty();
		}
		this.datatable = new frappe.DataTable(this.$table.get(0), {
			columns: this.current_columns,
			data: rows,
			layout: "fixed",
			direction: "rtl",
			serialNoColumn: false,
			checkboxColumn: false,
			inlineFilters: true,
			disableReorderColumn: false,
			noDataMessage: empty_message,
			events: {
				onSwitchColumn: () => {
					this.persist_columns();
					this.after_table_refresh();
				},
				onResizeColumn: () => {
					this.persist_columns();
					this.sync_column_geometry();
				},
				onSortColumn: () => this.after_table_refresh(),
			},
		});
		this.after_table_refresh();
		this.bind_row_click();
		this.bind_column_persist();
		this.bind_live_column_resize();
		this.bind_header_sort();
		this.bind_geometry_resize();
	}

	after_table_refresh() {
		this.show_column_filters();
		this.sync_column_geometry();
	}

	sync_column_geometry() {
		if (!this.datatable || !this.datatable.datamanager || !this.$table) {
			return;
		}
		const columns = this.datatable.datamanager.getColumns() || [];
		let total = 0;
		columns.forEach((col) => {
			if (!col || col.colIndex == null) {
				return;
			}
			const is_key = col.id === "key";
			const width = is_key ? 0 : cint(col.width);
			if (!is_key) {
				total += width;
			}
			this.$table.find(".dt-cell--col-" + col.colIndex).each((_, el) => {
				el.style.flex = "0 0 " + width + "px";
				el.style.flexGrow = "0";
				el.style.flexShrink = "0";
				el.style.width = width + "px";
				el.style.minWidth = width + "px";
				el.style.maxWidth = width + "px";
				el.style.boxSizing = "border-box";
				if (is_key) {
					el.style.display = "none";
					el.style.overflow = "hidden";
					el.style.border = "0";
					el.style.padding = "0";
				}
				el.querySelectorAll(".dt-cell__content, .dt-cell__edit").forEach((content) => {
					content.style.width = width + "px";
					content.style.minWidth = width + "px";
					content.style.maxWidth = width + "px";
					content.style.boxSizing = "border-box";
				});
			});
		});
		this.$table.find(".dt-row").each((_, el) => {
			el.style.width = total + "px";
			el.style.minWidth = total + "px";
			el.style.maxWidth = "none";
			el.style.flexWrap = "nowrap";
		});
		this.$table.find(".dt-header, .dt-header > div").each((_, el) => {
			el.style.width = total + "px";
			el.style.minWidth = total + "px";
			el.style.maxWidth = "none";
			el.style.overflow = "visible";
		});
		if (this.datatable.style && typeof this.datatable.style.setStyle === "function") {
			this.datatable.style.setStyle(".dt-row", {
				width: total + "px",
				"min-width": total + "px",
				"max-width": "none",
				"flex-wrap": "nowrap",
			});
		}
		if (this.datatable.style && typeof this.datatable.style.setBodyStyle === "function") {
			this.datatable.style.setBodyStyle();
		}
	}

	bind_geometry_resize() {
		$(window)
			.off("resize.sp-explorer")
			.on(
				"resize.sp-explorer",
				frappe.utils.debounce(() => {
					if (!this.datatable) {
						return;
					}
					this.sync_column_geometry();
				}, 150)
			);
	}

	show_column_filters() {
		if (!this.datatable || !this.datatable.columnmanager) {
			return;
		}
		this.datatable.columnmanager.toggleFilter(true);
		this.$table.find(".dt-row-filter .dt-cell--col-0").hide();
	}

	bind_header_sort() {
		this.$table.off("click.sp-sort").on("click.sp-sort", ".dt-cell--header", (event) => {
			if ($(event.target).closest(".dt-cell__resize-handle, .dt-dropdown, .dt-filter").length) {
				return;
			}
			event.preventDefault();
			event.stopPropagation();
			if (!this.datatable || !this.datatable.datamanager) {
				return;
			}
			const $cell = $(event.currentTarget);
			const from_class = ($cell.attr("class") || "").match(/dt-cell--header-(\d+)/);
			const colIndex = cint($cell.attr("data-col-index") || (from_class && from_class[1]));
			const column = this.datatable.datamanager.getColumn(colIndex);
			if (!column || column.id === "key" || column.sortable === false) {
				return;
			}
			const next = { none: "asc", asc: "desc", desc: "none" }[column.sortOrder || "none"] || "asc";
			this.datatable.sortColumn(colIndex, next);
		});
	}

	apply_saved_layout(columns, kind) {
		const saved = this.column_settings[kind] || {};
		const by_id = {};
		columns.forEach((col) => {
			by_id[col.id] = Object.assign({}, col);
			if (saved.widths && saved.widths[col.id]) {
				by_id[col.id].width = saved.widths[col.id];
			}
		});
		const ordered = [];
		const seen = new Set();
		ordered.push(by_id.key);
		seen.add("key");
		(saved.order || []).forEach((id) => {
			if (id !== "key" && by_id[id] && !seen.has(id)) {
				ordered.push(by_id[id]);
				seen.add(id);
			}
		});
		columns.forEach((col) => {
			if (!seen.has(col.id) && by_id[col.id]) {
				ordered.push(by_id[col.id]);
			}
		});
		return ordered;
	}

	persist_columns() {
		if (!this.datatable || !this.datatable.datamanager) {
			return;
		}
		const columns = this.datatable.datamanager.columns || [];
		const order = [];
		const widths = {};
		columns.forEach((col) => {
			if (!col || !col.id || col.id === "key") {
				return;
			}
			order.push(col.id);
			if (col.width) {
				widths[col.id] = cint(col.width);
			}
		});
		this.column_settings[this.current_kind] = { order, widths };
		try {
			localStorage.setItem(this.local_settings_key(), JSON.stringify(this.column_settings));
		} catch (e) {
			/* ignore quota */
		}
		try {
			if (frappe.model.user_settings && typeof frappe.model.user_settings.save === "function") {
				frappe.model.user_settings.save(this.settings_key, "column_settings", this.column_settings);
			}
		} catch (e) {
			console.warn(e);
		}
	}

	bind_column_persist() {
		this.$table.off("mouseup.sp-col").on("mouseup.sp-col", ".dt-cell__resize-handle", () => {
			setTimeout(() => {
				this.sync_column_geometry();
				this.persist_columns();
			}, 50);
		});
	}

	bind_live_column_resize() {
		$(document)
			.off("mousemove.sp-explorer-resize mouseup.sp-explorer-resize")
			.on("mousemove.sp-explorer-resize", () => {
				if (!document.body.classList.contains("dt-resize") || !this.datatable) {
					return;
				}
				this.sync_column_geometry();
			})
			.on("mouseup.sp-explorer-resize", () => {
				if (!this.datatable) {
					return;
				}
				this.sync_column_geometry();
			});
	}

	bind_row_click() {
		this.$table.off("click.sp-explorer").on("click.sp-explorer", ".dt-cell", (event) => {
			if (
				$(event.target).closest(
					".dt-cell--header, .dt-cell--filter, .dt-filter, .dt-row-filter, .sort-indicator"
				).length
			) {
				return;
			}
			const $link = $(event.target).closest(".sp-source-link");
			if ($link.length) {
				event.preventDefault();
				event.stopPropagation();
				const doctype = $link.attr("data-doctype");
				const name = $link.attr("data-name");
				if (doctype && name) {
					frappe.set_route("Form", doctype, name);
				}
				return;
			}
			const $row = $(event.target).closest(".dt-row");
			if ($row.attr("data-is-header") || $row.hasClass("dt-row-filter")) {
				return;
			}
			const key = ($row.find(".dt-cell--col-0 .dt-cell__content").text() || "").trim();
			if (this.mode === "overview") {
				const row = this.balances.find((item) => item.party === key);
				if (row) {
					this.open_ledger(row);
				}
				return;
			}
			event.preventDefault();
			const row = this.lines[cint(key)];
			if (row) {
				this.show_detail(row);
			}
		});
	}

	visible_columns() {
		const live =
			this.datatable && this.datatable.datamanager ? this.datatable.datamanager.columns || [] : [];
		const from_live = live.filter((col) => col && col.id && col.id !== "key");
		if (from_live.length) {
			return from_live;
		}
		return (this.current_columns || []).filter((col) => col.id && col.id !== "key");
	}

	export_table() {
		const columns = this.visible_columns();
		if (!columns.length || !this.current_rows || !this.current_rows.length) {
			return null;
		}
		const header = columns.map((col) => this.plain_text(col.name));
		const data_rows = this.current_rows.map((row) => {
			const by_id = {};
			this.current_columns.forEach((col, idx) => {
				let value = row[idx];
				if (typeof col.format === "function") {
					value = col.format(value);
				}
				by_id[col.id] = this.plain_text(value);
			});
			return columns.map((col) => by_id[col.id] ?? "");
		});
		return { header, data_rows };
	}

	export_filename(ext) {
		const ctx = this.ledger_context || {};
		const stamp = frappe.datetime.now_datetime().replace(/[: ]/g, "-");
		return `${ctx.party || "party-account"}-${stamp}.${ext}`;
	}

	export_title() {
		if (this.mode === "ledger") {
			const ctx = this.ledger_context || {};
			return [__("گردش طرف حساب"), ctx.party_name || ctx.party || ""].filter(Boolean).join(" — ");
		}
		return __("مانده طرف حساب");
	}

	export_subtitle() {
		const parts = [
			this.company.get_value(),
			this.currency.get_value(),
			this.mode === "ledger"
				? `${this.from_date.get_value() || ""} — ${this.to_date.get_value() || ""}`
				: this.as_of_date.get_value() || "",
		];
		return parts.filter(Boolean).join(" | ");
	}

	export_excel() {
		const table = this.export_table();
		if (!table) {
			frappe.msgprint(__("داده‌ای برای خروجی نیست."));
			return;
		}
		open_url_post(frappe.request.url, {
			cmd: "smartprocess_erpnext_accounting.smartprocess_accounting.party_account.excel_export.export_explorer_xlsx",
			columns: JSON.stringify(table.header),
			rows: JSON.stringify(table.data_rows),
			filename: this.export_filename("xlsx"),
		});
	}

	export_pdf() {
		const table = this.export_table();
		if (!table) {
			frappe.msgprint(__("داده‌ای برای خروجی نیست."));
			return;
		}
		open_url_post(frappe.request.url, {
			cmd: "smartprocess_erpnext_accounting.smartprocess_accounting.party_account.excel_export.export_explorer_pdf",
			columns: JSON.stringify(table.header),
			rows: JSON.stringify(table.data_rows),
			filename: this.export_filename("pdf"),
			title: this.export_title(),
			subtitle: this.export_subtitle(),
		});
	}

	plain_text(value) {
		if (value === null || value === undefined) {
			return "";
		}
		return $("<div>").html(String(value)).text();
	}

	csv_cell(value) {
		const text = String(value ?? "").replace(/"/g, '""');
		return `"${text}"`;
	}

	show_detail(row) {
		const ctx = this.ledger_context || {};
		frappe.call({
			method:
				"smartprocess_erpnext_accounting.smartprocess_accounting.party_account.document_details.get_document_detail",
			args: {
				voucher_type: row.voucher_type,
				voucher_no: row.voucher_no,
				party_type: ctx.party_type || this.party_type.get_value(),
				party: ctx.party,
				account: row.account,
				against_voucher_type: row.against_voucher_type,
				against_voucher: row.against_voucher,
				posting_date: row.posting_date,
				debit: row.debit_base,
				credit: row.credit_base,
				against: row.against,
				remarks: row.remarks,
			},
			freeze: true,
			callback: (r) => this.open_dialog(r.message || {}, row),
		});
	}

	open_dialog(detail, row) {
		const html = this.render_detail_html(detail);
		const dialog = new frappe.ui.Dialog({
			title: detail.title || row.voucher_no,
			size: "large",
			fields: [{ fieldtype: "HTML", fieldname: "body" }],
			primary_action_label: __("باز کردن سند"),
			primary_action: () => {
				if (detail.can_open && detail.doctype && detail.name) {
					frappe.set_route("Form", detail.doctype, detail.name);
				}
				dialog.hide();
			},
		});
		dialog.fields_dict.body.$wrapper.html(html);
		if (!detail.can_open) {
			dialog.get_primary_btn().hide();
		}
		dialog.show();
	}

	render_detail_html(detail) {
		const summary = (detail.summary || [])
			.filter((item) => item.value !== null && item.value !== undefined && item.value !== "")
			.map(
				(item) =>
					`<tr><th>${frappe.utils.escape_html(item.label)}</th><td>${frappe.utils.escape_html(
						String(item.value)
					)}</td></tr>`
			)
			.join("");
		let html = `<table class="table table-bordered table-condensed">${summary}</table>`;
		html += this.render_detail_table(__("اقلام"), detail.items, detail.item_columns);
		html += this.render_detail_table(__("مالیات و عوارض"), detail.taxes, detail.tax_columns);
		html += this.render_detail_table(__("اسناد مرجع"), detail.references, detail.reference_columns);
		html += this.render_accounts(detail.accounts, detail.account_columns);
		html += this.render_detail_table(__("ردیف‌های تبدیل"), detail.rows, detail.row_columns);
		html += this.render_linked_documents(detail.linked_documents);
		return html;
	}

	render_linked_documents(documents) {
		if (!documents || !documents.length) {
			return "";
		}
		let html = `<h4>${__("اسناد مرتبط")}</h4>`;
		documents.forEach((doc) => {
			const title = [doc.title || doc.doctype, doc.name].filter(Boolean).join(" — ");
			html += `<h5>${frappe.utils.escape_html(title)}</h5>`;
			html += this.render_detail_table(__("اقلام"), doc.items, doc.item_columns);
			html += this.render_detail_table(__("مالیات و عوارض"), doc.taxes, doc.tax_columns);
			html += this.render_detail_table(__("اسناد مرجع"), doc.references, doc.reference_columns);
			html += this.render_accounts(doc.accounts, doc.account_columns);
		});
		return html;
	}

	render_detail_table(title, rows, columns) {
		if (!rows || !rows.length || !columns || !columns.length) {
			return "";
		}
		const head = columns
			.map((col) => `<th>${frappe.utils.escape_html(col.label)}</th>`)
			.join("");
		const body = rows
			.map((row) => {
				const cells = columns
					.map((col) => `<td>${frappe.utils.escape_html(String(row[col.key] ?? ""))}</td>`)
					.join("");
				return `<tr>${cells}</tr>`;
			})
			.join("");
		return `<h5>${frappe.utils.escape_html(title)}</h5><table class="table table-bordered table-condensed"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
	}

	render_accounts(rows, columns) {
		if (!rows || !rows.length || !columns || !columns.length) {
			return "";
		}
		const head = columns
			.map((col) => `<th>${frappe.utils.escape_html(col.label)}</th>`)
			.join("");
		const body = rows
			.map((row) => {
				const cells = columns
					.map((col) => `<td>${frappe.utils.escape_html(String(row[col.key] ?? ""))}</td>`)
					.join("");
				const mark = row.is_party_row ? ' class="active"' : "";
				return `<tr${mark}>${cells}</tr>`;
			})
			.join("");
		return `<h5>${__("ردیف‌های سند حسابداری")}</h5><table class="table table-bordered table-condensed"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
	}

	format_amount(value, currency) {
		if (value === null || value === undefined || value === "") {
			return "";
		}
		return format_number(value, null, currency_precision(currency));
	}
}
