"""Display labels for Party Account Explorer. No Frappe imports."""

ACCOUNTING_DOCUMENT = "SmartProcess Accounting Document"
ACCOUNTING_POSTING = "SmartProcess Accounting Posting"
RECEIPT_CONVERSION = "SmartProcess Receipt Conversion"

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

OPERATION_LABELS = {
	"Receipt": "رسید",
	"Payment": "پرداخت",
}

CONVERSION_MODE_LABELS = {
	"Receipt": "تبدیل از رسید",
	"Balance": "تبدیل از مانده حساب",
}

# doctype → (label, return label)
VOUCHER_LABELS = {
	"Sales Invoice": ("فاکتور فروش", "برگشت از فروش"),
	"Purchase Invoice": ("فاکتور خرید", "برگشت از خرید"),
	"Delivery Note": ("حواله فروش", "برگشت حواله فروش"),
	"Purchase Receipt": ("رسید خرید", "برگشت رسید خرید"),
	"Journal Entry": ("سند حسابداری", None),
	"Payment Entry": ("دریافت/پرداخت", None),
	"Stock Entry": ("سند انبار", None),
	RECEIPT_CONVERSION: ("تبدیل ارز", None),
	"SmartProcess Currency Conversion": ("تبدیل ارز (قدیمی)", None),
	ACCOUNTING_POSTING: ("ثبت حسابداری", None),
	ACCOUNTING_DOCUMENT: ("سند عملیات", None),
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


def voucher_label(doctype, is_return=False, operation_type=None):
	if operation_type in OPERATION_LABELS:
		return OPERATION_LABELS[operation_type]
	label, return_label = VOUCHER_LABELS.get(doctype, (None, None))
	if is_return and return_label:
		return return_label
	return label


def invoice_kind_label(doctype, is_return):
	return voucher_label(doctype, is_return) or doctype


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
