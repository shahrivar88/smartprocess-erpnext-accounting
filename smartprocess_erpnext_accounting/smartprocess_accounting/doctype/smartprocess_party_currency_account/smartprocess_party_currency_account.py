from __future__ import annotations

from hashlib import sha256

import frappe
from frappe import _
from frappe.model.document import Document

from smartprocess_erpnext_accounting.smartprocess_accounting.v2_validation import (
	get_company_currency,
	validate_account,
	validate_party,
)


class SmartProcessPartyCurrencyAccount(Document):
	def autoname(self):
		identity = "|".join((self.party_type, self.party, self.company, self.currency))
		self.name = f"SP-PCA-{sha256(identity.encode()).hexdigest()[:24]}"

	def validate(self):
		get_company_currency(self.company)
		if not frappe.db.exists("Currency", self.currency):
			frappe.throw(_("Currency {0} does not exist.").format(self.currency))
		account = validate_account(self.account, self.company)
		validate_party(self.party_type, self.party, account.account_type)
		if account.account_currency != self.currency:
			frappe.throw(_("Mapped Currency must match Account.account_currency."))
		duplicate = frappe.db.exists(
			self.doctype,
			{
				"party_type": self.party_type,
				"party": self.party,
				"company": self.company,
				"currency": self.currency,
				"name": ["!=", self.name],
			},
		)
		if duplicate:
			frappe.throw(_("Only one Account mapping is allowed for this Party, Company, and Currency."))
