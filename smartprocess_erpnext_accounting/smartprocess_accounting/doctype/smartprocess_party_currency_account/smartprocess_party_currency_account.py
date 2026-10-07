"""DEPRECATED: the multi-currency Party design is retired.

One Party record carries exactly one accounting currency; a second currency needs a
separate Party record. The DocType and its table stay for historical reference only.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

RETIRED_MESSAGE = (
	"«حساب ارزی طرف حساب» منسوخ شده است و قابل ثبت یا ویرایش نیست؛ "
	"برای هر ارز یک رکورد طرف حساب جداگانه با حساب همان ارز بسازید."
)


class SmartProcessPartyCurrencyAccount(Document):
	def validate(self):
		frappe.throw(_(RETIRED_MESSAGE))

	def on_trash(self):
		frappe.throw(_(RETIRED_MESSAGE))
