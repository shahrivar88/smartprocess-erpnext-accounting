# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Customer/Supplier offset through a standard Journal Entry. No bank, no extra GL."""

from __future__ import annotations

from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import flt, getdate

from smartprocess_erpnext_accounting.smartprocess_accounting.decimal_utils import decimal_text, to_decimal

REMARK_PREFIX = "SmartProcess offset:"
INVOICE_TYPES = {"Customer": "Sales Invoice", "Supplier": "Purchase Invoice"}
PARTY_ACCOUNT_TYPES = {"Customer": "Receivable", "Supplier": "Payable"}


def preview_offset(payload: dict) -> dict:
	left = _side(payload, "receivable")
	right = _side(payload, "payable")
	if left.company != right.company:
		frappe.throw(_("تهاتر بین دو شرکت مجاز نیست."))
	if left.currency != right.currency:
		frappe.throw(_("تهاتر چندارزی در این نسخه فعال نیست."))
	if left.rate != right.rate:
		frappe.throw(_("نرخ ارز دو طرف تهاتر باید یکسان باشد."))
	requested = to_decimal(payload.get("amount") or min(left.outstanding, right.outstanding), _("Amount"))
	amount = min(requested, left.outstanding, right.outstanding)
	if amount <= 0:
		frappe.throw(_("مبلغ تهاتر باید بزرگ‌تر از صفر و حداکثر برابر مانده هر فاکتور باشد."))
	company_amount = (amount * left.rate).quantize(Decimal("0.000001"))
	return {
		"company": left.company,
		"currency": left.currency,
		"amount": decimal_text(amount),
		"company_amount": decimal_text(company_amount),
		"exchange_rate": decimal_text(left.rate),
		"receivable": left.as_dict(),
		"payable": right.as_dict(),
	}


def submit_offset(payload: dict) -> str:
	plan = preview_offset(payload)
	if not frappe.has_permission("Journal Entry", "create"):
		frappe.throw(_("اجازه ساخت سند حسابداری را ندارید."), frappe.PermissionError)
	_lock_invoice(plan["receivable"]["voucher_type"], plan["receivable"]["voucher_no"])
	_lock_invoice(plan["payable"]["voucher_type"], plan["payable"]["voucher_no"])
	amount = flt(plan["amount"])
	company_amount = flt(plan["company_amount"])
	receivable = plan["receivable"]
	payable = plan["payable"]
	entry = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": plan["company"],
			"posting_date": getdate(payload.get("posting_date")),
			"multi_currency": int(plan["currency"] != frappe.get_cached_value("Company", plan["company"], "default_currency")),
			"user_remark": f"{REMARK_PREFIX} {receivable['voucher_no']} / {payable['voucher_no']}",
			"accounts": [
				{
					"account": payable["account"],
					"party_type": "Supplier",
					"party": payable["party"],
					"debit_in_account_currency": amount,
					"debit": company_amount,
					"exchange_rate": flt(plan["exchange_rate"]),
					"reference_type": payable["voucher_type"],
					"reference_name": payable["voucher_no"],
					"user_remark": REMARK_PREFIX,
				},
				{
					"account": receivable["account"],
					"party_type": "Customer",
					"party": receivable["party"],
					"credit_in_account_currency": amount,
					"credit": company_amount,
					"exchange_rate": flt(plan["exchange_rate"]),
					"reference_type": receivable["voucher_type"],
					"reference_name": receivable["voucher_no"],
					"user_remark": REMARK_PREFIX,
				},
			],
		}
	)
	entry.insert()
	entry.submit()
	return entry.name


class _Side:
	def __init__(self, **values):
		self.__dict__.update(values)

	def as_dict(self):
		return {
			"party_type": self.party_type,
			"party": self.party,
			"account": self.account,
			"currency": self.currency,
			"voucher_type": self.voucher_type,
			"voucher_no": self.voucher_no,
			"outstanding": decimal_text(self.outstanding),
		}


def _side(payload: dict, kind: str) -> _Side:
	party_type = "Customer" if kind == "receivable" else "Supplier"
	voucher_type = INVOICE_TYPES[party_type]
	party = payload.get(f"{kind}_party")
	account = payload.get(f"{kind}_account")
	voucher_no = payload.get(f"{kind}_invoice")
	if not party or not account or not voucher_no:
		frappe.throw(_("طرف {0} ناقص است.").format(party_type))
	if not frappe.has_permission(party_type, "read", doc=party):
		frappe.throw(_("اجازه خواندن این طرف‌حساب را ندارید."), frappe.PermissionError)
	if not frappe.has_permission(voucher_type, "read", doc=voucher_no):
		frappe.throw(_("اجازه خواندن این فاکتور را ندارید."), frappe.PermissionError)
	invoice = frappe.db.get_value(
		voucher_type,
		voucher_no,
		["name", "company", "docstatus", "outstanding_amount", "conversion_rate", "party_account_currency"],
		as_dict=True,
	)
	if not invoice or invoice.docstatus != 1:
		frappe.throw(_("فاکتور {0} ثبت نهایی نیست.").format(voucher_no))
	party_field = "customer" if party_type == "Customer" else "supplier"
	if frappe.db.get_value(voucher_type, voucher_no, party_field) != party:
		frappe.throw(_("فاکتور {0} به این طرف‌حساب تعلق ندارد.").format(voucher_no))
	details = frappe.get_cached_value(
		"Account",
		account,
		["company", "account_currency", "account_type"],
		as_dict=True,
	)
	if not details or details.company != invoice.company:
		frappe.throw(_("حساب {0} با شرکت فاکتور سازگار نیست.").format(account))
	if details.account_type != PARTY_ACCOUNT_TYPES[party_type]:
		frappe.throw(_("نوع حساب {0} برای {1} مناسب نیست.").format(account, party_type))
	currency = invoice.party_account_currency or details.account_currency
	if currency != details.account_currency:
		frappe.throw(_("ارز فاکتور {0} با ارز حساب یکی نیست.").format(voucher_no))
	return _Side(
		party_type=party_type,
		party=party,
		account=account,
		currency=currency,
		voucher_type=voucher_type,
		voucher_no=voucher_no,
		company=invoice.company,
		outstanding=to_decimal(invoice.outstanding_amount, _("Outstanding Amount")),
		rate=to_decimal(invoice.conversion_rate or 1, _("Exchange Rate")),
	)


def _lock_invoice(doctype: str, name: str) -> None:
	if doctype not in INVOICE_TYPES.values():
		frappe.throw(_("قفل تهاتر فقط برای فاکتور فروش یا خرید مجاز است."))
	frappe.db.sql("select name from `tab{0}` where name=%s for update".format(doctype), name)
