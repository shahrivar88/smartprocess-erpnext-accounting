// HTML for the two explorer tables. Every column has a stable key and a default
// width (overridable per user). Ledger rows stay in chronological order: no column
// sorts, because the running balance only holds in that order. Plain columns show
// the GL company-currency amounts, «ارزی» columns the GL account-currency amounts.
const pae_ledger_view = {
	columns(context) {
		return [
			{ key: "number", label: __("ردیف"), width: 64 },
			{ key: "date", label: __("تاریخ"), width: 104 },
			{ key: "document", label: __("نوع برگه"), width: 230 },
			{ key: "description", label: __("شرح"), width: 220 },
			{ key: "title", label: __("عنوان قلم"), width: 200 },
			{ key: "qty", label: __("مقدار"), width: 80, numeric: true },
			{ key: "rate_base", label: __("فی"), width: 130, numeric: true },
			{ key: "debit_base", label: __("بدهکار"), width: 140, numeric: true },
			{ key: "credit_base", label: __("بستانکار"), width: 140, numeric: true },
			{ key: "balance_base", label: __("مانده"), width: 150, numeric: true },
			{ key: "rate", label: __("فی ارزی"), width: 120, numeric: true },
			{ key: "debit", label: __("بدهکار ارزی"), width: 130, numeric: true },
			{ key: "credit", label: __("بستانکار ارزی"), width: 130, numeric: true },
			{ key: "balance", label: __("مانده ارزی"), width: 140, numeric: true },
			{ key: "actions", label: __("جزئیات"), width: 230, help: __("حساب معین و سندی که این ردیف دفتر کل را ثبت کرده است") },
		];
	},

	header(context, summary) {
		const currency = context.currency;
		const base = context.company_currency;
		const kpi = (label, value_base, value, extra, nature) => `<div class="sp-kpi ${extra || ""}">
			<div class="sp-kpi-label">${label}</div>
			<div class="sp-kpi-value">${pae_format.amount(value_base, base, true)} <span class="sp-kpi-currency">${pae_format.text(base)}</span>${nature ? ` <span class="sp-kpi-nature">${pae_format.text(nature)}</span>` : ""}</div>
			<div class="sp-kpi-base">${__("ارزی")}: ${pae_format.amount(value, currency, true)} ${pae_format.text(currency)}</div>
		</div>`;
		const period = `${pae_format.date(context.from_date) || __("ابتدا")} ${__("تا")} ${pae_format.date(context.to_date)}`;
		const meta = (label, value) => `<span class="sp-meta-item"><span class="sp-meta-label">${label}</span>${value}</span>`;
		const warning = summary.other_currency_rows
			? `<div class="sp-ledger-warning">${__(
					"{0} ردیف با ارزی غیر از ارز حساب ثبت شده است. همه ردیف‌ها نمایش داده می‌شوند و این ردیف‌ها برچسب «ارز ثبت» دارند.",
					[summary.other_currency_rows]
			  )}</div>`
			: "";
		return `<div class="sp-ledger-header">
			<div class="sp-ledger-identity">
				<div class="sp-ledger-party">${pae_format.text(context.party_name)}</div>
				<div class="sp-ledger-meta">
					${meta(__("شرکت"), pae_format.text(context.company))}
					${meta(__("ارز حساب"), pae_format.text(currency))}
					${context.account ? meta(__("حساب"), pae_format.text(context.account)) : ""}
					${meta(__("دوره"), period)}
				</div>
			</div>
			<div class="sp-kpis">
				${kpi(__("مانده اول دوره"), summary.opening_base, summary.opening)}
				${kpi(__("گردش بدهکار"), summary.period_debit_base, summary.period_debit)}
				${kpi(__("گردش بستانکار"), summary.period_credit_base, summary.period_credit)}
				${kpi(__("مانده پایان دوره"), summary.closing_base, summary.closing, "sp-kpi-strong", summary.nature)}
			</div>
			${warning}
		</div>`;
	},

	toolbar(filters) {
		const side = (value, label) => `<option value="${value}" ${filters.side === value ? "selected" : ""}>${label}</option>`;
		return `<div class="sp-ledger-toolbar">
			<input type="search" class="form-control input-xs sp-ledger-search" value="${pae_format.text(filters.search || "")}" placeholder="${__("جستجو در شماره، نوع برگه، شرح، کالا، سند ثبت…")}">
			<select class="form-control input-xs sp-ledger-side">
				${side("", __("همه ردیف‌ها"))}${side("debit", __("فقط بدهکار"))}${side("credit", __("فقط بستانکار"))}
			</select>
			<span class="sp-ledger-status text-muted small"></span>
		</div>`;
	},

	// Filtering runs on the whole period server-side; shown balances remain the real
	// chronological balances after each row.
	status(filters, totals, currency, company_currency) {
		if (!pae_ledger_rows.is_filtered(filters) || !totals) {
			return "";
		}
		const base = company_currency || currency;
		return `${__("{0} ردیف دفتر کل مطابق فیلتر", [totals.row_count])} ·
			${__("بدهکار")} ${pae_format.amount(totals.debit_base, base, true)} ·
			${__("بستانکار")} ${pae_format.amount(totals.credit_base, base, true)} ·
			${__("بدهکار ارزی")} ${pae_format.amount(totals.debit, currency, true)} ·
			${__("بستانکار ارزی")} ${pae_format.amount(totals.credit, currency, true)} ·
			${__("مانده هر ردیف، مانده واقعی پس از آن ردیف به ترتیب زمانی است")}
			<button class="btn btn-link btn-xs sp-clear-view">${__("حذف فیلتر")}</button>`;
	},

	colgroup(columns, prefs, table) {
		return `<colgroup>${columns.map((column) => `<col data-col="${column.key}" style="width:${prefs.width(table, column.key, column.width)}px">`).join("")}</colgroup>`;
	},

	head(columns) {
		return columns
			.map((column) => {
				const help = column.help ? ` title="${pae_format.text(column.help)}"` : "";
				return `<th data-col="${column.key}" data-default-width="${column.width}"${help}>${pae_format.text(column.label)}</th>`;
			})
			.join("");
	},

	voucher(voucher) {
		const number = pae_format.link(voucher.doctype, voucher.name, voucher.number);
		const detail = voucher.detail ? `<span class="sp-voucher-detail">${pae_format.text(voucher.detail)}</span>` : "";
		return `${number}${detail}`;
	},

	// «جزئیات»: the GL line's own account and posting voucher, and the drill-down button.
	details(row) {
		if (!row.first) {
			return "<td></td>";
		}
		const account = row.account ? `<div class="sp-detail-account" title="${pae_format.text(row.account)}">${pae_format.text(row.account)}</div>` : "";
		return `<td class="sp-details-cell">
			${account}
			<div class="sp-voucher">${pae_ledger_view.voucher(row.voucher)}</div>
			<button class="btn btn-default btn-xs sp-detail-btn">${__("جزئیات")}</button>
		</td>`;
	},

	cell(key, row, context) {
		const currency = context.currency;
		const base = context.company_currency;
		switch (key) {
			case "number":
				return `<td class="text-muted sp-cell-number">${pae_format.text(row.number)}</td>`;
			case "date":
				return `<td>${pae_format.date(row.date)}</td>`;
			case "document":
				return `<td>${pae_format.document(row.doc)}</td>`;
			case "description":
				return `<td class="sp-remarks">${pae_format.text(row.description)}${pae_ledger_view.badges(row.badges)}</td>`;
			case "title":
				return `<td class="sp-component-title">${pae_format.text(row.title)}</td>`;
			case "qty":
				return `<td>${pae_format.number(row.qty)}</td>`;
			case "rate_base":
				return `<td>${pae_format.amount(row.rate_base, base)}</td>`;
			case "rate":
				return `<td>${pae_format.amount(row.rate, currency)}</td>`;
			case "debit_base":
			case "credit_base":
				return `<td>${pae_format.amount(row[key], base)}</td>`;
			case "debit":
			case "credit":
				return `<td>${pae_format.amount(row[key], currency)}</td>`;
			case "balance_base":
				return `<td class="sp-strong">${pae_format.amount(row.balance_base, base, true)}</td>`;
			case "balance":
				return `<td class="sp-strong">${pae_format.amount(row.balance, currency, true)}</td>`;
			case "actions":
				return pae_ledger_view.details(row);
			default:
				return "<td></td>";
		}
	},

	badges(badges) {
		return (badges || [])
			.map((badge) =>
				badge.type === "posted"
					? `<span class="sp-badge sp-badge-warn">${__("ارز ثبت")}: ${pae_format.text(badge.currency)}</span>`
					: `<span class="sp-badge">${__("ارز سند")}: ${pae_format.text(badge.currency)} ${pae_format.amount(badge.amount, badge.currency, true)}</span>`
			)
			.join("");
	},

	group_rows(group, columns, context) {
		return group.rows
			.map((row) => {
				const css = ["sp-gl-row", `sp-kind-${row.kind}`, row.first ? "sp-group-first" : "", row.last ? "sp-group-last" : ""].join(" ");
				return `<tr class="${css}" data-gl="${pae_format.text(row.gl_entry)}">${columns.map((column) => pae_ledger_view.cell(column.key, row, context)).join("")}</tr>`;
			})
			.join("");
	},

	// Opening / carry-forward / totals rows: a label in the document column, amounts in place.
	balance_row(css, columns, context, values) {
		const base_keys = ["debit_base", "credit_base", "balance_base"];
		const cells = columns.map((column) => {
			if (column.key === "document") {
				return `<td class="sp-strong">${pae_format.text(values.label)}${values.nature ? ` <span class="sp-kpi-nature">${pae_format.text(values.nature)}</span>` : ""}</td>`;
			}
			if (column.key === "date") {
				return `<td>${pae_format.date(values.date)}</td>`;
			}
			if (column.key in values && (base_keys.includes(column.key) || ["debit", "credit", "balance"].includes(column.key))) {
				const currency = base_keys.includes(column.key) ? context.company_currency : context.currency;
				return `<td class="sp-strong">${pae_format.amount(values[column.key], currency, true)}</td>`;
			}
			return "<td></td>";
		});
		return `<tr class="${css}">${cells.join("")}</tr>`;
	},

	overview_columns() {
		return [
			{ key: "party", label: __("طرف حساب"), width: 240 },
			{ key: "currency", label: __("ارز حساب"), width: 110 },
			{ key: "period_debit_base", label: __("گردش بدهکار"), width: 150, numeric: true },
			{ key: "period_credit_base", label: __("گردش بستانکار"), width: 150, numeric: true },
			{ key: "closing_base", label: __("مانده"), width: 160, numeric: true },
			{ key: "period_debit", label: __("گردش بدهکار ارزی"), width: 150, numeric: true },
			{ key: "period_credit", label: __("گردش بستانکار ارزی"), width: 150, numeric: true },
			{ key: "closing", label: __("مانده ارزی"), width: 160, numeric: true },
		];
	},

	// One overview cell; `row` is a party row or a per-currency total row.
	overview_cell(key, row, company_currency) {
		switch (key) {
			case "party":
				return `<td><span class="sp-party-name">${pae_format.text(row.party_name)}</span></td>`;
			case "currency":
				return `<td>${pae_ledger_view.currency_cell(row.currency, row.other_currency_rows)}</td>`;
			case "period_debit_base":
			case "period_credit_base":
				return `<td>${pae_format.amount(row[key], company_currency, true)}</td>`;
			case "closing_base":
				return `<td class="sp-strong">${pae_format.amount(row.closing_base, company_currency, true)}</td>`;
			case "period_debit":
			case "period_credit":
				return `<td>${pae_format.amount(row[key], row.currency, true)}</td>`;
			case "closing":
				return `<td class="sp-strong">${pae_format.amount(row.closing, row.currency, true)}</td>`;
			default:
				return "<td></td>";
		}
	},

	currency_cell(currency, other_currency_rows) {
		const badge = other_currency_rows
			? ` <span class="sp-badge sp-badge-warn" title="${__("این ردیف‌ها نمایش داده می‌شوند؛ فقط ارز ثبت آن‌ها با ارز حساب فرق دارد.")}">${__("{0} ردیف با ارز دیگر", [other_currency_rows])}</span>`
			: "";
		return `${pae_format.text(currency)}${badge}`;
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = { pae_ledger_view };
}
