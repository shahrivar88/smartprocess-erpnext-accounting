# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""Report period and the GL SUM columns shared by the balance overview and the ledger."""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from .access import GL
from .labels import balance_nature

EARLIEST = "0001-01-01"
SIDES = (
	("", "debit_in_account_currency", "credit_in_account_currency"),
	("_base", "debit", "credit"),
)


class Period:
	def __init__(self, from_date=None, to_date=None):
		self.from_date = getdate(from_date) if from_date else None
		self.to_date = getdate(to_date) if to_date else getdate(nowdate())
		if self.from_date and self.from_date > self.to_date:
			frappe.throw(_("از تاریخ نباید بعد از تا تاریخ باشد."))

	@property
	def params(self):
		return {"from_date": self.from_date or EARLIEST, "to_date": self.to_date}

	@property
	def until(self):
		return f" and {GL}.posting_date <= %(to_date)s"

	@property
	def inside(self):
		return f" and {GL}.posting_date between %(from_date)s and %(to_date)s"

	def as_dict(self):
		return {"from_date": self.from_date, "to_date": self.to_date}


def balance_columns():
	"""Opening is everything before from_date; it is never part of period movement."""
	columns = []
	for suffix, debit, credit in SIDES:
		columns += [
			f"sum(case when {GL}.posting_date < %(from_date)s then {GL}.{debit} - {GL}.{credit} else 0 end) as opening{suffix}",
			f"sum(case when {GL}.posting_date >= %(from_date)s then {GL}.{debit} else 0 end) as period_debit{suffix}",
			f"sum(case when {GL}.posting_date >= %(from_date)s then {GL}.{credit} else 0 end) as period_credit{suffix}",
		]
	return ", ".join(columns)


def balance_values(row):
	values = {}
	for suffix, _debit, _credit in SIDES:
		opening = flt(row.get(f"opening{suffix}"))
		debit = flt(row.get(f"period_debit{suffix}"))
		credit = flt(row.get(f"period_credit{suffix}"))
		values.update(
			{
				f"opening{suffix}": opening,
				f"period_debit{suffix}": debit,
				f"period_credit{suffix}": credit,
				f"closing{suffix}": flt(opening + debit - credit, 9),
			}
		)
	values["nature"] = balance_nature(values["closing"])
	return values
