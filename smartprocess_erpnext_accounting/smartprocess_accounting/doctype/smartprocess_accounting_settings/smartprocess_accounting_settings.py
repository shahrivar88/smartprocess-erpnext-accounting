import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_number_format_info


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
	meta = frappe.get_meta("SmartProcess Accounting Settings")
	settings = frappe.get_single("SmartProcess Accounting Settings")

	enabled = settings.enable_live_number_separator
	if enabled is None:
		enabled = cint(meta.get_field("enable_live_number_separator").default)
	separator = settings.number_separator or meta.get_field("number_separator").default or ","

	number_format = frappe.get_system_settings("number_format") or "#,###.##"
	decimal_str, group_str, _precision = get_number_format_info(number_format)

	return {
		"enabled": cint(enabled),
		"separator": separator,
		"decimal_str": decimal_str,
		"group_str": group_str,
	}
