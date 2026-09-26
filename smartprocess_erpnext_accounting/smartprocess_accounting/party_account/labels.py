"""Display labels for Party Account Explorer. No Frappe imports."""

PAYMENT_TYPE_LABELS = {
	"Receive": "دریافت",
	"Pay": "پرداخت",
	"Internal Transfer": "انتقال داخلی",
}

DOCSTATUS_LABELS = {
	0: "پیش‌نویس",
	1: "ارسال‌شده",
	2: "لغو شده",
}


def doc_get(doc, key, default=None):
	if doc is None:
		return default
	if hasattr(doc, "get"):
		value = doc.get(key)
		return default if value is None else value
	return getattr(doc, key, default)


def payment_type_label(payment_type):
	if not payment_type:
		return ""
	return PAYMENT_TYPE_LABELS.get(payment_type, payment_type)


def invoice_kind_label(doctype, is_return):
	if doctype == "Sales Invoice":
		return "برگشت از فروش" if is_return else "فاکتور فروش"
	if doctype == "Purchase Invoice":
		return "برگشت از خرید" if is_return else "فاکتور خرید"
	return doctype


def docstatus_label(docstatus):
	try:
		return DOCSTATUS_LABELS[int(docstatus)]
	except (TypeError, ValueError, KeyError):
		return ""


def balance_nature(amount):
	value = float(amount or 0)
	if abs(value) < 0.0000001:
		return "تسویه"
	if value > 0:
		return "بدهکار"
	return "بستانکار"


def apply_running_balance(opening, rows, debit_key="debit", credit_key="credit"):
	"""Stage 1 running balance: opening + cumulative (debit - credit)."""
	running = float(opening or 0)
	out = []
	for row in rows:
		debit = float(row.get(debit_key) or 0)
		credit = float(row.get(credit_key) or 0)
		running = running + debit - credit
		item = dict(row)
		item["debit"] = debit
		item["credit"] = credit
		item["running_balance"] = running
		item["balance_nature"] = balance_nature(running)
		out.append(item)
	return float(opening or 0), out
