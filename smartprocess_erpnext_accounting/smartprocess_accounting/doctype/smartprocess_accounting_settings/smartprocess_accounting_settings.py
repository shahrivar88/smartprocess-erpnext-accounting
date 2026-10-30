import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_number_format_info

from smartprocess_erpnext_accounting.smartprocess_accounting.default_accounts import (
	is_enabled as central_default_accounts_enabled,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.default_accounts import (
	validate_default_account_settings,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.shareholder_accounting import (
	cross_app_impacts as shareholder_cross_app_impacts,
)
from smartprocess_erpnext_accounting.smartprocess_accounting.shareholder_accounting import (
	flags as shareholder_flags,
)

SETTINGS = "SmartProcess Accounting Settings"

# Independent display keys: master Check AND per-DocType Check. Slug is the
# suffix of hide_trailing_zeros_<slug> / live_separator_<slug>.
DISPLAY_DOCTYPE_KEYS = (
	("sales_invoice", "Sales Invoice", "فاکتور فروش"),
	("purchase_invoice", "Purchase Invoice", "فاکتور خرید"),
	("quotation", "Quotation", "پیش‌فاکتور"),
	("sales_order", "Sales Order", "سفارش فروش"),
	("purchase_order", "Purchase Order", "سفارش خرید"),
)

# Already wired (Payment Entry) or owned by this app. They follow the master
# flag only; no extra Settings Check is created for them.
MASTER_FOLLOW_DOCTYPES = (
	"Payment Entry",
	"SmartProcess Accounting Document",
	"SmartProcess Accounting Posting",
	"SmartProcess Receipt Conversion",
	"SmartProcess Currency Conversion",
)


class SmartProcessAccountingSettings(Document):
	def validate(self):
		self.validate_number_separator()
		validate_default_account_settings(self)

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


@frappe.whitelist(methods=["POST"])
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
		df = frappe.get_meta(SETTINGS).get_field(fieldname)
		value = df.default if df else 0
	return cint(value)


def hide_insignificant_trailing_zeros():
	return display_flag("hide_insignificant_trailing_zeros")


def settlement_flag():
	if not frappe.get_meta(SETTINGS).has_field("enable_payment_entry_settlement"):
		return 0
	return display_flag("enable_payment_entry_settlement")


def doctype_display_map(master_field, prefix):
	"""DocType → 1 only when the master Check and that DocType Check are both on."""
	master = display_flag(master_field)
	mapping = {}
	for slug, doctype, _label in DISPLAY_DOCTYPE_KEYS:
		mapping[doctype] = 1 if master and display_flag(f"{prefix}_{slug}") else 0
	for doctype in MASTER_FOLLOW_DOCTYPES:
		mapping[doctype] = 1 if master else 0
	return mapping


def _stored(doctype):
	return frappe.db.get_singles_dict(doctype, cast=False)


def cross_app_impacts():
	"""Desk-facing inventory of features that reach outside this module."""
	zeros_map = doctype_display_map("hide_insignificant_trailing_zeros", "hide_trailing_zeros")
	sep_map = doctype_display_map("enable_live_number_separator", "live_separator")
	zeros_on = [label for slug, doctype, label in DISPLAY_DOCTYPE_KEYS if zeros_map.get(doctype)]
	sep_on = [label for slug, doctype, label in DISPLAY_DOCTYPE_KEYS if sep_map.get(doctype)]
	return [
		{
			"feature": "حذف صفرهای اعشاری غیرضروری",
			"owner_module": "رسید هوشمند",
			"doctypes": "، ".join(zeros_on) or "هیچ سندی",
			"effect": "فقط متن نمایش اعداد را در فرم و جدول ردیف کوتاه می‌کند. مقدار ذخیره‌شده، دقت و محاسبات تغییر نمی‌کنند.",
			"status": "فعال" if hide_insignificant_trailing_zeros() else "غیرفعال",
			"rollback": "کلید اصلی یا کلید همان سند را در «نمایش اعداد» خاموش کنید تا رفتار استاندارد ERPNext برگردد.",
			"optional": 1,
		},
		{
			"feature": "جداکننده زنده هزارگان",
			"owner_module": "رسید هوشمند",
			"doctypes": "، ".join(sep_on) or "هیچ سندی",
			"effect": "هنگام ورود عدد، جداکننده هزارگان را فقط در ورودی نشان می‌دهد. مقدار خام ارسالی به سرور بدون جداکننده می‌ماند.",
			"status": "فعال" if display_flag("enable_live_number_separator") else "غیرفعال",
			"rollback": "کلید اصلی یا کلید همان سند را در «نمایش اعداد» خاموش کنید تا ورودی استاندارد ERPNext برگردد.",
			"optional": 1,
		},
		{
			"feature": "حساب‌های پیش‌فرض مرکزی",
			"owner_module": "رسید هوشمند",
			"doctypes": "فاکتور فروش، فاکتور خرید",
			"effect": "در پیش‌نویس غیربرگشتی، حساب دریافتنی یا پرداختنی هم‌شرکت و هم‌ارز جدول تنظیمات را به‌جای پیشنهاد خودکار ERPNext پیشنهاد می‌کند. انتخاب دستی و اسناد ثبت‌شده تغییر نمی‌کنند.",
			"status": "فعال" if cint(central_default_accounts_enabled()) else "غیرفعال",
			"rollback": "گزینه «فعال‌سازی حساب‌های پیش‌فرض مرکزی» را خاموش کنید.",
			"optional": 1,
		},
		{
			"feature": "جلوگیری از ثبت فاکتور با حساب معین غیرهم‌ارز",
			"owner_module": "رسید هوشمند",
			"doctypes": "فاکتور فروش",
			"effect": "ثبت نهایی فاکتور فروش فقط وقتی انجام می‌شود که ارز حساب دریافتنی با ارز صورتحساب یکی باشد. هیچ حسابی خودکار عوض نمی‌شود.",
			"status": "فعال" if display_flag("prevent_receivable_currency_mismatch") else "غیرفعال",
			"rollback": "گزینه «جلوگیری از ثبت فاکتور با حساب معین غیرهم‌ارز» را خاموش کنید.",
			"optional": 1,
		},
		{
			"feature": "الزام ورود دستی نرخ تبدیل فاکتور",
			"owner_module": "رسید هوشمند",
			"doctypes": "فاکتور فروش، فاکتور خرید",
			"effect": "در فاکتور ارزی، نرخ خودکار پاک می‌شود تا کاربر نرخ را دستی وارد کند. فاکتور بدون نرخ بزرگ‌تر از صفر ذخیره نمی‌شود.",
			"status": "فعال" if display_flag("enable_manual_invoice_rate_feature") else "غیرفعال",
			"rollback": "گزینه «الزام ورود دستی نرخ تبدیل فاکتور» را خاموش کنید.",
			"optional": 1,
		},
		{
			"feature": "محافظ حذف شرکت و اسناد وابسته",
			"owner_module": "رسید هوشمند",
			"doctypes": "Transaction Deletion Record، شرکت، اسناد اختصاصی حسابداری، واسطه مالی",
			"effect": "حذف شرکت یا اجرای Transaction Deletion Record وقتی سند اختصاصی یا واسطه مالی به آن شرکت وصل است متوقف می‌شود. این محافظ مالی است و کلید خاموش‌کردن ناامن ندارد.",
			"status": "فعال (محافظ الزامی)",
			"rollback": "غیرفعال‌سازی از تنظیمات مجاز نیست. فقط با مجوز جداگانه و تغییر کنترل‌شده در اپ.",
			"optional": 0,
		},
		{
			"feature": "محافظ حذف اپ حسابداری",
			"owner_module": "رسید هوشمند",
			"doctypes": "تمام اسناد اختصاصی حسابداری",
			"effect": "حذف اپ وقتی سند اختصاصی باقی مانده باشد متوقف می‌شود تا دفتر کل یتیم نشود.",
			"status": "فعال (محافظ الزامی)",
			"rollback": "غیرفعال‌سازی از تنظیمات مجاز نیست.",
			"optional": 0,
		},
		{
			"feature": "قفل آزمایشگاهی نویسنده استاندارد",
			"owner_module": "رسید هوشمند",
			"doctypes": "رسید هوشمند، پرداخت، سند حسابداری (فقط آزمایشگاه)",
			"effect": "فقط روی سایت آزمایشگاهی و با پرچم جداگانه فعال می‌شود. روی این سایت زنده خاموش است و بدون تأیید جداگانه روشن نمی‌شود.",
			"status": "غیرفعال روی این سایت",
			"rollback": "فعال‌سازی روی سایت زنده نیاز به تأیید جداگانه دارد. کلید خاموش‌کردن در تنظیمات وجود ندارد.",
			"optional": 0,
		},
		{
			"feature": "تسویه فاکتور با سند دریافت و پرداخت استاندارد",
			"owner_module": "رسید هوشمند",
			"doctypes": "رسید هوشمند، سند دریافت، سند پرداخت، فاکتور فروش، فاکتور خرید",
			"effect": "دریافت و پرداخت ساده مشتری یا تأمین‌کننده یک سند دریافت یا پرداخت استاندارد می‌سازد و مانده فاکتور را از دفتر تسویه رسمی کم می‌کند. ثبت حسابداری موازی برای همان گردش ساخته نمی‌شود.",
			"status": "فعال" if settlement_flag() else "غیرفعال",
			"rollback": "گزینه «تسویه فاکتور با سند دریافت و پرداخت استاندارد» را خاموش کنید. اسناد ثبت‌شده قبلی تغییر نمی‌کنند.",
			"optional": 1,
		},
		*shareholder_cross_app_impacts(),
	]


def extend_bootinfo(bootinfo):
	"""Desk flags, read once per page load. UI only: no server rule reads them."""
	bootinfo.smartprocess_accounting = {
		"hide_insignificant_trailing_zeros": hide_insignificant_trailing_zeros(),
		"allow_exchange_rate_editing": display_flag("allow_exchange_rate_editing"),
		"live_number_separator": number_input_settings(),
		"central_default_accounts": cint(central_default_accounts_enabled()),
		"hide_trailing_zeros_doctypes": doctype_display_map(
			"hide_insignificant_trailing_zeros", "hide_trailing_zeros"
		),
		"live_separator_doctypes": doctype_display_map("enable_live_number_separator", "live_separator"),
		"cross_app_impacts": cross_app_impacts(),
		"shareholder_accounting": shareholder_flags(),
		"payment_entry_settlement": settlement_flag(),
	}
