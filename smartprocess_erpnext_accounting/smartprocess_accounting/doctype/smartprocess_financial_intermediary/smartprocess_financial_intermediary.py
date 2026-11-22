import frappe
from frappe.model.document import Document

from smartprocess_erpnext_accounting.smartprocess_accounting.party_account.party_profile import (
	guard_party_deletion,
	load_party_onload,
	validate_party_master,
)

SETTINGS_DOCTYPE = "SmartProcess Accounting Settings"
NAMING_SERIES_FIELD = "intermediary_naming_series"
DEFAULT_NAMING_SERIES = "SP-FI-.YYYY.-.#####"


class SmartProcessFinancialIntermediary(Document):
	def before_naming(self):
		self.naming_series = self._configured_series()

	def _configured_series(self):
		"""The Settings value, else the module default; existing names never change."""
		return frappe.get_single_value(SETTINGS_DOCTYPE, NAMING_SERIES_FIELD) or DEFAULT_NAMING_SERIES

	def onload(self):
		load_party_onload(self)

	def validate(self):
		validate_party_master(self)

	def on_trash(self):
		guard_party_deletion(self)
