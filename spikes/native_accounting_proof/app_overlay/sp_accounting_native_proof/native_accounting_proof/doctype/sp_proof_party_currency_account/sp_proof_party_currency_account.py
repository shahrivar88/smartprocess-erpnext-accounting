"""Proof-only Party, Company, Currency, and Account mapping."""

from __future__ import annotations

from hashlib import sha256

import frappe
from frappe import _
from frappe.model.document import Document


class SPProofPartyCurrencyAccount(Document):
	def autoname(self):
		identity = "|".join((self.party_type, self.party, self.company, self.currency))
		self.name = f"SP-PCA-{sha256(identity.encode()).hexdigest()[:24]}"

	def validate(self):
		self._validate_party()
		self._validate_account()

	def _validate_party(self):
		if not frappe.db.exists(self.party_type, self.party):
			frappe.throw(_("Party {0} {1} does not exist.").format(self.party_type, self.party))

	def _validate_account(self):
		account = frappe.get_cached_value(
			"Account",
			self.account,
			["company", "account_currency", "account_type", "disabled", "is_group"],
			as_dict=True,
		)
		if not account:
			frappe.throw(_("Account {0} does not exist.").format(self.account))
		if account.company != self.company:
			frappe.throw(_("Mapped Account must belong to the selected Company."))
		if account.account_currency != self.currency:
			frappe.throw(_("Mapped Currency must match Account.account_currency."))
		if account.disabled:
			frappe.throw(_("Mapped Account must be enabled."))
		if account.is_group:
			frappe.throw(_("Mapped Account must not be a group Account."))

		party_account_type = frappe.get_cached_value("Party Type", self.party_type, "account_type")
		if not party_account_type or party_account_type != account.account_type:
			frappe.throw(
				_("Mapped Account type must match Party Type account type {0}.").format(
					party_account_type or _("Receivable or Payable")
				)
			)
