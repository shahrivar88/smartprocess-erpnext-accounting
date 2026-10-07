// Read-only document summary shown in the ledger's details dialog; the dialog's
// primary action opens the full document.
const pae_detail_view = {
	title(detail) {
		const heading = detail.title || __("جزئیات سند");
		return detail.document ? `${heading} — ${detail.document.name}` : heading;
	},

	html(detail) {
		return [
			pae_detail_view.items(detail.summary),
			detail.focus && detail.focus.length ? `<h6 class="sp-detail-title">${__("ردیف انتخاب‌شده")}</h6>${pae_detail_view.items(detail.focus, "sp-focus")}` : "",
			...(detail.sections || []).map((section) => pae_detail_view.section(section)),
			pae_detail_view.related(detail.related),
			detail.technical && detail.technical.length
				? `<details class="sp-technical"><summary>${__("اطلاعات فنی")}</summary>${pae_detail_view.items(detail.technical)}</details>`
				: "",
		].join("");
	},

	loading() {
		return `<div class="text-muted small">${__("در حال بارگذاری جزئیات…")}</div>`;
	},

	failed() {
		return `<div class="text-muted small">${__("جزئیات این سند قابل نمایش نیست.")}</div>`;
	},

	value(entry) {
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
	},

	items(items, extra_class) {
		if (!items || !items.length) {
			return "";
		}
		return `<div class="sp-detail-grid ${extra_class || ""}">${items
			.map((entry) => `<div class="sp-detail-item"><div class="text-muted small">${pae_format.text(entry.label)}</div><div>${pae_detail_view.value(entry)}</div></div>`)
			.join("")}</div>`;
	},

	section(section) {
		const head = section.columns.map((column) => `<th>${pae_format.text(column.label)}</th>`).join("");
		const rows = section.rows
			.map((row) => {
				const cells = section.columns
					.map((column) => `<td>${pae_detail_view.value({ kind: column.kind, value: row[column.key], doctype: row[`${column.key}_doctype`] })}</td>`)
					.join("");
				return `<tr class="${row.is_current ? "sp-row-current" : ""}">${cells}</tr>`;
			})
			.join("");
		return `<h6 class="sp-detail-title">${pae_format.text(section.title)}</h6>
			<div class="sp-detail-table"><table class="table table-bordered sp-table"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>
			${section.note ? `<p class="text-muted small">${pae_format.text(section.note)}</p>` : ""}`;
	},

	related(related) {
		if (!related || !related.length) {
			return "";
		}
		return `<h6 class="sp-detail-title">${__("اسناد مرتبط")}</h6><ul class="sp-related">${related
			.map((entry) => `<li>${pae_format.text(entry.relation)}: ${pae_format.link(entry.doctype, entry.name)} <span class="text-muted small">(${pae_format.text(entry.label)})</span></li>`)
			.join("")}</ul>`;
	},
};

if (typeof module === "object" && module.exports) {
	module.exports = { pae_detail_view };
}
