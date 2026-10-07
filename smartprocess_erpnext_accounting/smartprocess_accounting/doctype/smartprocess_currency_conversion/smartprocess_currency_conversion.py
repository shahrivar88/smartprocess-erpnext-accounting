# Copyright (c) 2026, Smart Process and contributors
# For license information, please see license.txt

"""DEPRECATED: replaced by SmartProcess Receipt Conversion.

The DocType and its table stay for historical compatibility only; this controller
never posts, saves or cancels a document again.
"""

import frappe
from frappe import _
from frappe.model.document import Document

RETIRED_MESSAGE = "«تبدیل ارز (قدیمی)» منسوخ شده است؛ از «تبدیل ارز» (SmartProcess Receipt Conversion) استفاده کنید."


class SmartProcessCurrencyConversion(Document):
	def validate(self):
		frappe.throw(_(RETIRED_MESSAGE))

	def before_cancel(self):
		frappe.throw(_(RETIRED_MESSAGE))
