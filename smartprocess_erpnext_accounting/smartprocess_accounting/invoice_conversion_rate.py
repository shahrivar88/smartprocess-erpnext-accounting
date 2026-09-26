# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Validate invoice conversion_rate. Does not change ERPNext calculations."""

import frappe
from frappe import _

from smartprocess_erpnext_accounting.smartprocess_accounting.invoice_conversion_rate_check import (
	needs_manual_conversion_rate,
)

MSG_MANUAL_RATE = "نرخ تبدیل ارز را به‌صورت دستی وارد کنید."


def validate_conversion_rate(doc, method=None):
	company_currency = frappe.get_cached_value("Company", doc.company, "default_currency")
	if needs_manual_conversion_rate(doc.currency, company_currency, doc.conversion_rate):
		frappe.throw(_(MSG_MANUAL_RATE))
