# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Company-aware ledger period helpers. No Telegram knowledge."""

import frappe
from frappe import _
from frappe.utils import getdate


def get_current_fiscal_year_to_date(company, as_of_date=None):
	"""Return (year_start_date, as_of_date) for the Company's Fiscal Year containing as_of_date.

	Uses ERPNext ``erpnext.accounts.utils.get_fiscal_year`` — never hard-codes
	January 1, March 21, or Jalali boundaries.

	Raises ``frappe.ValidationError`` with a Persian message when no Fiscal Year
	covers the date for that Company (does not guess a range).
	"""
	if not company:
		frappe.throw(_("شرکت الزامی است."))

	as_of = getdate(as_of_date) if as_of_date else getdate()
	from erpnext.accounts.utils import FiscalYearError, get_fiscal_year

	try:
		fy = get_fiscal_year(
			date=as_of,
			company=company,
			as_dict=True,
			verbose=0,
			raise_on_missing=True,
		)
	except FiscalYearError:
		frappe.throw(
			_("سال مالی معتبری برای شرکت {0} در تاریخ {1} یافت نشد.").format(
				frappe.bold(company), frappe.format(as_of, {"fieldtype": "Date"})
			)
		)

	if not fy or not getattr(fy, "year_start_date", None):
		frappe.throw(
			_("سال مالی معتبری برای شرکت {0} در تاریخ {1} یافت نشد.").format(
				frappe.bold(company), frappe.format(as_of, {"fieldtype": "Date"})
			)
		)

	return getdate(fy.year_start_date), as_of
