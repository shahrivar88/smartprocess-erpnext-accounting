import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_number_format_info

SETTINGS = "SmartProcess Accounting Settings"

class SmartProcessAccountingSettings(Document):
	def validate(self):
		self.validate_number_separator()

	def validate_number_separator(self):
		separator = self.number_separator
		enabled = cint(self.enable_live_number_separator)

		if not separator:
			if enabled:
				frappe.throw(_("برای فعال‌سازی جداکننده زنده، «جداکننده اعداد» را تعیین کنید."))
			return
		if len(separator) != 1:
			frappe.throw(_("جداکننده اعداد باید دقیقاً یک کاراکتر باشد."))
		if separator.isdigit():
			frappe.throw(_("جداکننده اعداد نمی‌تواند رقم باشد."))
		# «.» is not hard-coded here: it is rejected only when it equals the site's
		# real decimal separator (checked below from System Settings), so it stays
		# valid as a thousands separator on sites whose decimal separator is «,».
		if separator in "+-*/()":
			frappe.throw(_("کاراکتر «{0}» به‌عنوان جداکننده اعداد مجاز نیست.").format(separator))
		if separator in ("e", "E"):
			frappe.throw(
				_("کاراکتر «{0}» به‌عنوان جداکننده اعداد مجاز نیست (تداخل با نماد علمی).").format(separator)
			)
		decimal_str, _group_str, _precision = get_number_format_info(
			frappe.get_system_settings("number_format") or "#,###.##"
		)
		if separator == decimal_str:
			frappe.throw(
				_("جداکننده اعداد نمی‌تواند با جداکننده اعشار ({0}) یکی باشد.").format(decimal_str)
			)


@frappe.whitelist()
def get_number_input_settings():
	"""Live number-separator config for client-side numeric inputs (presentation only)."""
	return number_input_settings()


def number_input_settings():
	meta = frappe.get_meta(SETTINGS)
	separator = _stored(SETTINGS).get("number_separator") or meta.get_field("number_separator").default or ","

	number_format = frappe.get_system_settings("number_format") or "#,###.##"
	decimal_str, group_str, _precision = get_number_format_info(number_format)

	return {
		"enabled": display_flag("enable_live_number_separator"),
		"separator": separator,
		"decimal_str": decimal_str,
		"group_str": group_str,
	}


def display_flag(fieldname):
	"""A display-only Check of the Settings; a value never saved yet uses the field default."""
	value = _stored(SETTINGS).get(fieldname)
	if value is None:
		value = frappe.get_meta(SETTINGS).get_field(fieldname).default
	return cint(value)


def hide_insignificant_trailing_zeros():
	return display_flag("hide_insignificant_trailing_zeros")


def _stored(doctype):
	return frappe.db.get_singles_dict(doctype, cast=False)


def extend_bootinfo(bootinfo):
	"""Desk display flags, read once per page load. UI only: no server rule reads them."""
	bootinfo.smartprocess_accounting = {
		"hide_insignificant_trailing_zeros": hide_insignificant_trailing_zeros(),
		"allow_exchange_rate_editing": display_flag("allow_exchange_rate_editing"),
		"live_number_separator": number_input_settings(),
	}
