# Copyright (c) 2026, Smart Process and contributors

from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.invoice_lines import (
	ITEM_COLUMNS,
	TAX_COLUMNS,
	invoice_item_rows,
	invoice_tax_rows,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.labels import (
	doc_get,
	docstatus_label,
	invoice_kind_label,
)


def resolve_purchase_invoice(doc, context=None):
	is_return = bool(doc_get(doc, "is_return"))
	return {
		"resolver": "purchase_invoice",
		"title": invoice_kind_label("Purchase Invoice", is_return),
		"doctype": doc.doctype,
		"name": doc.name,
		"can_open": True,
		"is_return": is_return,
		"summary": [
			{"label": "شماره فاکتور", "value": doc.name},
			{"label": "تاریخ ثبت", "value": str(doc.posting_date or "")},
			{"label": "تأمین‌کننده", "value": doc.supplier},
			{"label": "شماره فاکتور تأمین‌کننده", "value": doc.bill_no or ""},
			{"label": "ارز", "value": doc.currency},
			{"label": "نرخ تبدیل", "value": doc_get(doc, "conversion_rate")},
			{"label": "جمع کل", "value": doc.grand_total},
			{"label": "مانده", "value": doc.outstanding_amount},
			{"label": "وضعیت سند", "value": docstatus_label(doc.docstatus)},
			{"label": "برگشت از خرید", "value": "بله" if is_return else "خیر"},
			{"label": "برگشت از", "value": doc.return_against if is_return else ""},
			{"label": "شرح", "value": doc_get(doc, "remarks") or ""},
		],
		"items": invoice_item_rows(doc),
		"item_columns": ITEM_COLUMNS,
		"taxes": invoice_tax_rows(doc),
		"tax_columns": TAX_COLUMNS,
	}
