// HTML for the two explorer tables. Every column has a stable key, a default width
// (overridable per user) and, when it can be sorted, a sort key.
const pae_ledger_view = {
	columns(context) {
		const columns = [
			{ key: "number", label: "#", width: 64, sort: "number" },
			{ key: "date", label: __("تاریخ"), width: 104, sort: "date" },
			{ key: "document", label: __("سند"), width: 250, sort: "document" },
			{ key: "description", label: __("شرح"), width: 240 },
			{ key: "title", label: __("عنوان قلم"), width: 220 },
			{ key: "qty", label: __("مقدار"), width: 80, numeric: true },
			{ key: "rate", label: __("فی"), width: 130, numeric: true },
			{ key: "debit", label: __("بدهکار"), width: 140, sort: "debit", numeric: true },
			{ key: "credit", label: __("بستانکار"), width: 140, sort: "credit", numeric: true },
		];
		if (context.is_foreign) {
			columns.push({ key: "posting_rate", label: __("نرخ ثبت"), width: 110, numeric: true });
		}
		columns.push(
			{ key: "balance", label: __("مانده"), width: 150, numeric: true },
			{ key: "nature", label: __("ماهیت"), width: 90 },
			{ key: "detail_ref", label: __("ردیف سند"), width: 170 }
		);
		if (context.is_foreign) {
			columns.push({ key: "balance_base", label: __("مانده {0}", [context.company_currency]), width: 160, numeric: true });
		}
		columns.push({ key: "actions", label: "", width: 90 });
		return columns;
	},

	header(context, summary) {
		const currency = context.currency;
		const base = context.company_currency;
		const kpi = (label, value, value_base, extra, nature) => `<div class="sp-kpi ${extra || ""}">
			<div class="sp-kpi-label">${label}</div>
			<div class="sp-kpi-value">${pae_format.amount(value, currency, true)}${nature ? ` <span class="sp-kpi-nature">${pae_format.text(nature)}</span>` : ""}</div>
			${context.is_foreign ? `<div class="sp-kpi-base">${pae_format.amount(value_base, base, true)} ${pae_format.text(base)}</div>` : ""}
		</div>`;
		const period = `${pae_format.date(context.from_date) || __("ابتدا")} ${__("تا")} ${pae_format.date(context.to_date)}`;
		const meta = (label, value) => `<span class="sp-meta-item"><span class="sp-meta-label">${label}</span>${value}</span>`;
		const warning = summary.other_currency_rows
			? `<div class="sp-ledger-warning">${__(
					"{0} ردیف این حساب با ارزی غیر از ارز حساب ثبت شده است. همه ردیف‌ها نمایش داده می‌شوند و این ردیف‌ها برچسب «ارز ثبت» دارند.",
					[summary.other_currency_rows]
			  )}</div>`
			: "";
		return `<div class="sp-ledger-header">
			<div class="sp-ledger-identity">
				<div class="sp-ledger-party">${pae_format.text(context.party_name)} <span class="sp-party-id">${pae_format.text(context.party)}</span></div>
				<div class="sp-ledger-meta">
					${meta(__("حساب"), pae_format.text(context.account))}
					${meta(__("شرکت"), pae_format.text(context.company))}
					${meta(__("ارز حساب"), pae_format.text(currency))}
					${meta(__("دوره"), period)}
				</div>
			</div>
			<div class="sp-kpis">
				${kpi(__("مانده اول دوره"), summary.opening, summary.opening_base)}
				${kpi(__("گردش بدهکار"), summary.period_debit, summary.period_debit_base)}
				${kpi(__("گردش بستانکار"), summary.period_credit, summary.period_credit_base)}
				${kpi(__("مانده پایان دوره"), summary.closing, summary.closing_base, "sp-kpi-strong", summary.nature)}
			</div>
			${warning}
		</div>`;
	},

	toolbar(state) {
		const side = (value, label) => `<option value="${value}" ${state.side === value ? "selected" : ""}>${label}</option>`;
		return `<div class="sp-ledger-toolbar">
			<input type="search" class="form-control input-xs sp-ledger-search" value="${pae_format.text(state.query || "")}" placeholder="${__("جستجو در سند، شرح، قلم…")}">
			<select class="form-control input-xs sp-ledger-side">
				${side("", __("همه ردیف‌ها"))}${side("debit", __("فقط بدهکار"))}${side("credit", __("فقط بستانکار"))}
			</select>
			<span class="sp-ledger-status text-muted small"></span>
		</div>`;
	},

	status(state, shown, total) {
		if (!pae_ledger_rows.is_filtered(state)) {
			return "";
		}
		return `${__("{0} از {1} سند این صفحه", [shown, total])} · ${__("مانده‌ها به ترتیب زمانی ثبت است")}
			<button class="btn btn-link btn-xs sp-clear-view">${__("حذف فیلتر و مرتب‌سازی")}</button>`;
	},

	colgroup(columns, prefs, table) {
		return `<colgroup>${columns.map((column) => `<col data-col="${column.key}" style="width:${prefs.width(table, column.key, column.width)}px">`).join("")}</colgroup>`;
	},

	head(columns, state) {
		return columns
			.map((column) => {
				const sorted = column.sort && state && state.sort_key === column.sort;
				const arrow = sorted ? (state.sort_dir === "desc" ? " ▼" : " ▲") : "";
				const sort_attr = column.sort ? ` data-sort="${column.sort}"` : "";
				const css = [column.sort ? "sp-sortable" : "", sorted ? "sp-sorted" : ""].join(" ");
				return `<th data-col="${column.key}" data-default-width="${column.width}"${sort_attr} class="${css}">${pae_format.text(column.label)}${arrow}</th>`;
			})
			.join("");
	},

	cell(key, row, context, open) {
		const currency = context.currency;
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
			case "rate":
				return `<td>${pae_format.amount(row.rate, currency)}</td>`;
			case "debit":
				return `<td>${pae_format.amount(row.debit, currency)}</td>`;
			case "credit":
				return `<td>${pae_format.amount(row.credit, currency)}</td>`;
			case "posting_rate":
				return `<td>${pae_format.rate(row.posting_rate)}</td>`;
			case "balance":
				return `<td class="sp-strong">${pae_format.amount(row.balance, currency, true)}</td>`;
			case "nature":
				return `<td>${pae_format.text(row.nature)}</td>`;
			case "detail_ref":
				return `<td class="small">${pae_format.text(row.detail_ref)}</td>`;
			case "balance_base":
				return `<td class="text-muted">${pae_format.amount(row.balance_base, context.company_currency, true)}</td>`;
			case "actions":
				return row.first
					? `<td><button class="btn btn-default btn-xs sp-detail-btn" aria-expanded="${open ? "true" : "false"}">${open ? __("بستن") : __("جزئیات")}</button></td>`
					: "<td></td>";
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

	group_rows(group, columns, context, open) {
		return group.rows
			.map((row) => {
				const css = ["sp-gl-row", `sp-kind-${row.kind}`, row.first ? "sp-group-first" : "", row.last ? "sp-group-last" : ""].join(" ");
				return `<tr class="${css}" data-gl="${pae_format.text(row.gl_entry)}">${columns.map((column) => pae_ledger_view.cell(column.key, row, context, open)).join("")}</tr>`;
			})
			.join("");
	},

	// Opening / carry-forward / totals rows: a label in the document column, amounts in place.
	balance_row(css, columns, context, values) {
		const cells = columns.map((column) => {
			if (column.key === "document") {
				return `<td class="sp-strong">${pae_format.text(values.label)}</td>`;
			}
			if (column.key === "date") {
				return `<td>${pae_format.date(values.date)}</td>`;
			}
			if (["debit", "credit", "balance"].includes(column.key) && column.key in values) {
				return `<td class="sp-strong">${pae_format.amount(values[column.key], context.currency, true)}</td>`;
			}
			if (column.key === "nature") {
				return `<td>${pae_format.text(values.nature)}</td>`;
			}
			if (column.key === "balance_base") {
				return `<td>${pae_format.amount(values.balance_base, context.company_currency, true)}</td>`;
			}
			return "<td></td>";
		});
		return `<tr class="${css}">${cells.join("")}</tr>`;
	},

	detail_row(gl_entry, columns, html) {
		return `<tr class="sp-detail-row" data-gl="${pae_format.text(gl_entry)}"><td colspan="${columns.length}"><div class="sp-detail-panel sp-detail">${html}</div></td></tr>`;
	},

	overview_columns(show_base, company_currency) {
		const columns = [
			{ key: "party", label: __("طرف حساب"), width: 240 },
			{ key: "account", label: __("حساب"), width: 220 },
			{ key: "currency", label: __("ارز حساب"), width: 120 },
			{ key: "opening", label: __("مانده اول دوره"), width: 150 },
			{ key: "period_debit", label: __("گردش بدهکار"), width: 150 },
			{ key: "period_credit", label: __("گردش بستانکار"), width: 150 },
			{ key: "closing", label: __("مانده پایان دوره"), width: 150 },
			{ key: "nature", label: __("ماهیت"), width: 90 },
		];
		if (show_base) {
			columns.push({ key: "closing_base", label: __("مانده پایان دوره ({0})", [company_currency]), width: 170 });
		}
		return columns;
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
