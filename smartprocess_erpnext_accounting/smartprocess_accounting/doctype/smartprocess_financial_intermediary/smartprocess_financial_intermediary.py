from frappe.model.document import Document

from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.party_profile import (
	guard_party_deletion,
	load_party_onload,
	validate_party_master,
)


class SmartProcessFinancialIntermediary(Document):
	def onload(self):
		load_party_onload(self)

	def validate(self):
		validate_party_master(self)

	def on_trash(self):
		guard_party_deletion(self)
