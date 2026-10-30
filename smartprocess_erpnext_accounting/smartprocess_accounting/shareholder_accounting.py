# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Optional Shareholder current-account paths. Capital stays on standard Share Transfer.

Every operational switch defaults off. Accounting validations are never optional.
Posted GL and historical documents are never rewritten.
"""

from frappe.utils import cint

import frappe
from frappe import _

from smartprocess_erpnext_accounting.smartprocess_accounting.default_accounts import get_default_account

SETTINGS = "SmartProcess Accounting Settings"
PARTY_TYPE = "Shareholder"
CURRENCY_FIELD = "custom_sp_default_currency"
CURRENT_PURPOSE = "Shareholder Current"

ENABLE_FIELD = "enable_shareholder_accounting"
SHOW_CURRENCY_FIELD = "show_shareholder_default_currency"
SUGGEST_ACCOUNT_FIELD = "suggest_shareholder_current_account"
SHOW_IN_DOCUMENT_FIELD = "show_shareholder_in_smart_document"
SHOW_IN_EXPLORER_FIELD = "show_shareholder_in_party_explorer"

CHILD_FIELDS = (
	SHOW_CURRENCY_FIELD,
	SUGGEST_ACCOUNT_FIELD,
	SHOW_IN_DOCUMENT_FIELD,
	SHOW_IN_EXPLORER_FIELD,
)

MSG_FEATURE_OFF = "نوع طرف حساب سهامدار در سند جدید مجاز نیست. این گزینه را در تنظیمات حسابداری هوشمند روشن کنید."
MSG_CURRENCY_LOCKED = (
	"سهامدار «{0}» گردش حسابداری با ارز {1} دارد. "
	"تغییر ارز پیش‌فرض به {2} با سیاست یک ارز برای هر طرف حساب سازگار نیست."
)
MSG_COMPANY = "سهامدار «{0}» متعلق به شرکت {1} است، نه شرکت {2}."
MSG_DISABLED_CURRENCY = "ارز {0} غیرفعال است."

CUSTOM_FIELDS = {
	PARTY_TYPE: [
		{
			"fieldname": CURRENCY_FIELD,
			"label": "ارز پیش‌فرض",
			"fieldtype": "Link",
			"options": "Currency",
			"insert_after": "company",
			"description": "فقط پیشنهاد ارز برای اسناد جدید است. ارز اسناد ثبت‌شده و گردش دفتر کل را تغییر نمی‌دهد.",
		}
	]
}


def flags():
	stored = _stored()
	enabled = cint(stored.get(ENABLE_FIELD))
	return {
		"enabled": enabled,
		"show_default_currency": enabled and cint(stored.get(SHOW_CURRENCY_FIELD)),
		"suggest_current_account": enabled and cint(stored.get(SUGGEST_ACCOUNT_FIELD)),
		"show_in_smart_document": enabled and cint(stored.get(SHOW_IN_DOCUMENT_FIELD)),
		"show_in_party_explorer": enabled and cint(stored.get(SHOW_IN_EXPLORER_FIELD)),
	}


def in_smart_document():
	return bool(flags()["show_in_smart_document"])


def show_in_explorer():
	return bool(flags()["show_in_party_explorer"])


def show_default_currency():
	return bool(flags()["show_default_currency"])


def assert_shareholder_allowed_for_new_posting(party_type):
	if party_type == PARTY_TYPE and not in_smart_document():
		frappe.throw(_(MSG_FEATURE_OFF))


def assert_shareholder_company(party, company):
	if not (party and company):
		return
	shareholder_company = frappe.db.get_value(PARTY_TYPE, party, "company")
	if shareholder_company and shareholder_company != company:
		frappe.throw(_(MSG_COMPANY).format(party, shareholder_company, company))


def suggested_current_account(company, currency):
	if not flags()["suggest_current_account"]:
		return None
	return get_default_account(company, currency, CURRENT_PURPOSE)


def suggested_currency(party):
	if not party or not frappe.get_meta(PARTY_TYPE).has_field(CURRENCY_FIELD):
		return None
	return frappe.db.get_value(PARTY_TYPE, party, CURRENCY_FIELD)


def validate_shareholder(doc, method=None):
	"""Preference field only. Posted GL is never rewritten from this form."""
	currency = doc.get(CURRENCY_FIELD)
	if currency:
		if not frappe.get_cached_value("Currency", currency, "enabled"):
			frappe.throw(_(MSG_DISABLED_CURRENCY).format(currency))
	if doc.is_new() or not doc.has_value_changed(CURRENCY_FIELD):
		return
	if not currency:
		return
	history = frappe.get_all(
		"GL Entry",
		filters={
			"party_type": PARTY_TYPE,
			"party": doc.name,
			"is_cancelled": 0,
			"account_currency": ["!=", currency],
		},
		pluck="account_currency",
		distinct=True,
	)
	if history:
		frappe.throw(_(MSG_CURRENCY_LOCKED).format(doc.name, ", ".join(history), currency))


def ensure_custom_fields():
	if not frappe.db.exists("DocType", PARTY_TYPE):
		return
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(CUSTOM_FIELDS, update=True)


def cross_app_impacts():
	state = flags()
	master = state["enabled"]

	def status(active):
		if not master:
			return "غیرفعال"
		return "فعال" if active else "غیرفعال"

	return [
		{
			"feature": "فعال‌سازی حسابداری سهامداران",
			"owner_module": "رسید هوشمند",
			"doctypes": "سهامدار، رسید هوشمند، تبدیل ارز، گردش حساب، تنظیمات حسابداری هوشمند",
			"effect": "کلید اصلی مسیرهای عملیاتی جدید سهامدار است. خاموش‌کردن آن GL تاریخی، سرمایه ثبت‌شده و فیلد ذخیره‌شده را حذف نمی‌کند.",
			"status": "فعال" if master else "غیرفعال",
			"rollback": "گزینه «فعال‌سازی حسابداری سهامداران» را خاموش کنید.",
			"optional": 1,
		},
		{
			"feature": "نمایش ارز پیش‌فرض در فرم سهامدار",
			"owner_module": "رسید هوشمند",
			"doctypes": "سهامدار",
			"effect": "فقط نمایش فیلد «ارز پیش‌فرض» در فرم سهامدار. مقدار ذخیره‌شده و GL تغییر نمی‌کنند.",
			"status": status(state["show_default_currency"]),
			"rollback": "گزینه «نمایش ارز پیش‌فرض در فرم سهامدار» را خاموش کنید. کلید اصلی باید روشن باشد تا این گزینه اثر داشته باشد.",
			"optional": 1,
		},
		{
			"feature": "پیشنهاد خودکار معین جاری سهامداران",
			"owner_module": "رسید هوشمند",
			"doctypes": "رسید هوشمند",
			"effect": "در رسید و پرداخت، حساب نگاشت‌شده «جاری سهامداران» را پیشنهاد می‌کند. انتخاب دستی و اعتبارسنجی ارز همچنان اجباری است.",
			"status": status(state["suggest_current_account"]),
			"rollback": "گزینه «پیشنهاد خودکار معین جاری سهامداران» را خاموش کنید.",
			"optional": 1,
		},
		{
			"feature": "نمایش سهامدار در رسید هوشمند",
			"owner_module": "رسید هوشمند",
			"doctypes": "رسید هوشمند، تبدیل ارز",
			"effect": "سهامدار را در انتخاب نوع طرف حساب اسناد جدید نشان می‌دهد. اسناد ثبت‌شده را تغییر نمی‌دهد.",
			"status": status(state["show_in_smart_document"]),
			"rollback": "گزینه «نمایش سهامدار در رسید هوشمند» را خاموش کنید.",
			"optional": 1,
		},
		{
			"feature": "نمایش سهامدار در گردش حساب اختصاصی",
			"owner_module": "رسید هوشمند",
			"doctypes": "گردش حساب",
			"effect": "گزینه فیلتر اختصاصی سهامدار را نشان می‌دهد. ردیف‌های GL تاریخی در نمای «همه انواع» می‌مانند.",
			"status": status(state["show_in_party_explorer"]),
			"rollback": "گزینه «نمایش سهامدار در گردش حساب اختصاصی» را خاموش کنید.",
			"optional": 1,
		},
	]


def _stored():
	return frappe.db.get_singles_dict(SETTINGS, cast=False)
