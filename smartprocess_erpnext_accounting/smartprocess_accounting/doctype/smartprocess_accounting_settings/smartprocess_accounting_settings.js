// Narrows the Account picker of a default account row. The server validates the final row.
const SP_DEFAULT_ACCOUNT_TYPES = { Receivable: "Receivable", Payable: "Payable", Bank: "Bank", Cash: "Cash" };
// Purpose labels are translated with this context so the global "Receivable"/"Payable" labels stay untouched.
const SP_DEFAULT_ACCOUNT_ROW = "SmartProcess Default Account";

function spPurposeLabel(value) {
	return value ? frappe.utils.escape_html(__(value, null, SP_DEFAULT_ACCOUNT_ROW)) : "";
}

function spDefaultAccountFilters(row, companyCurrency) {
	const filters = { is_group: 0, disabled: 0 };
	if (row.company) {
		filters.company = row.company;
	}
	if (row.currency) {
		// ERPNext treats an empty Account Currency as the company currency.
		const mayBeEmpty = !companyCurrency || row.currency === companyCurrency;
		filters.account_currency = mayBeEmpty ? ["in", [row.currency, null]] : row.currency;
	}
	if (SP_DEFAULT_ACCOUNT_TYPES[row.account_purpose]) {
		filters.account_type = SP_DEFAULT_ACCOUNT_TYPES[row.account_purpose];
	}
	return filters;
}

const SP_DISPLAY_DOCTYPE_KEYS = [
	["sales_invoice", "Sales Invoice"],
	["purchase_invoice", "Purchase Invoice"],
	["quotation", "Quotation"],
	["sales_order", "Sales Order"],
	["purchase_order", "Purchase Order"],
];
const SP_MASTER_FOLLOW_DOCTYPES = [
	"Payment Entry",
	"SmartProcess Accounting Document",
	"SmartProcess Accounting Posting",
	"SmartProcess Receipt Conversion",
	"SmartProcess Currency Conversion",
];

function spDoctypeDisplayMap(doc, masterField, prefix) {
	const master = Number(doc[masterField]) ? 1 : 0;
	const mapping = {};
	for (const [slug, doctype] of SP_DISPLAY_DOCTYPE_KEYS) {
		mapping[doctype] = master && Number(doc[`${prefix}_${slug}`]) ? 1 : 0;
	}
	for (const doctype of SP_MASTER_FOLLOW_DOCTYPES) {
		mapping[doctype] = master;
	}
	return mapping;
}

// Invoice forms read this flag from boot, which loads once per page; a save must reach this tab too.
function spSyncBootFlags(doc, boot) {
	const flags = boot && boot.smartprocess_accounting;
	if (!flags) {
		return;
	}
	if (doc.enable_central_default_accounts !== undefined) {
		flags.central_default_accounts = Number(doc.enable_central_default_accounts) ? 1 : 0;
	}
	if (doc.hide_insignificant_trailing_zeros !== undefined) {
		flags.hide_insignificant_trailing_zeros = Number(doc.hide_insignificant_trailing_zeros) ? 1 : 0;
	}
	if (doc.enable_live_number_separator !== undefined && flags.live_number_separator) {
		flags.live_number_separator.enabled = Number(doc.enable_live_number_separator) ? 1 : 0;
	}
	if (doc.hide_trailing_zeros_sales_invoice !== undefined) {
		flags.hide_trailing_zeros_doctypes = spDoctypeDisplayMap(
			doc,
			"hide_insignificant_trailing_zeros",
			"hide_trailing_zeros",
		);
	}
	if (doc.live_separator_sales_invoice !== undefined) {
		flags.live_separator_doctypes = spDoctypeDisplayMap(
			doc,
			"enable_live_number_separator",
			"live_separator",
		);
	}
}

function spEscape(text) {
	const value = text == null ? "" : String(text);
	if (typeof frappe !== "undefined" && frappe.utils?.escape_html) {
		return frappe.utils.escape_html(value);
	}
	return value.replace(/[&<>"']/g, (char) => ({
		"&": "&amp;",
		"<": "&lt;",
		">": "&gt;",
		'"': "&quot;",
		"'": "&#39;",
	}[char]));
}

function spFallbackCrossAppImpacts(doc) {
	const on = (value) => (Number(value) ? "فعال" : "غیرفعال");
	return [
		{
			feature: "حذف صفرهای اعشاری غیرضروری",
			owner_module: "حسابداری هوشمند",
			doctypes: "فاکتور فروش، فاکتور خرید، پیش‌فاکتور، سفارش فروش، سفارش خرید",
			effect: "فقط متن نمایش اعداد را در فرم و جدول ردیف کوتاه می‌کند. مقدار ذخیره‌شده، دقت و محاسبات تغییر نمی‌کنند.",
			status: on(doc.hide_insignificant_trailing_zeros),
			rollback: "کلید اصلی یا کلید همان سند را در «نمایش اعداد» خاموش کنید تا رفتار استاندارد ERPNext برگردد.",
			optional: 1,
		},
		{
			feature: "جداکننده زنده هزارگان",
			owner_module: "حسابداری هوشمند",
			doctypes: "فاکتور فروش، فاکتور خرید، پیش‌فاکتور، سفارش فروش، سفارش خرید",
			effect: "هنگام ورود عدد، جداکننده هزارگان را فقط در ورودی نشان می‌دهد. مقدار خام ارسالی به سرور بدون جداکننده می‌ماند.",
			status: on(doc.enable_live_number_separator),
			rollback: "کلید اصلی یا کلید همان سند را در «نمایش اعداد» خاموش کنید تا ورودی استاندارد ERPNext برگردد.",
			optional: 1,
		},
		{
			feature: "حساب‌های پیش‌فرض مرکزی",
			owner_module: "حسابداری هوشمند",
			doctypes: "فاکتور فروش، فاکتور خرید",
			effect: "در پیش‌نویس غیربرگشتی، حساب هم‌شرکت و هم‌ارز جدول تنظیمات را به‌جای پیشنهاد خودکار ERPNext پیشنهاد می‌کند.",
			status: on(doc.enable_central_default_accounts),
			rollback: "گزینه «فعال‌سازی حساب‌های پیش‌فرض مرکزی» را خاموش کنید.",
			optional: 1,
		},
		{
			feature: "جلوگیری از ثبت فاکتور با حساب معین غیرهم‌ارز",
			owner_module: "حسابداری هوشمند",
			doctypes: "فاکتور فروش",
			effect: "ثبت نهایی فاکتور فروش فقط وقتی انجام می‌شود که ارز حساب دریافتنی با ارز صورتحساب یکی باشد.",
			status: on(doc.prevent_receivable_currency_mismatch),
			rollback: "گزینه «جلوگیری از ثبت فاکتور با حساب معین غیرهم‌ارز» را خاموش کنید.",
			optional: 1,
		},
		{
			feature: "الزام ورود دستی نرخ تبدیل فاکتور",
			owner_module: "حسابداری هوشمند",
			doctypes: "فاکتور فروش، فاکتور خرید",
			effect: "در فاکتور ارزی، نرخ خودکار پاک می‌شود تا کاربر نرخ را دستی وارد کند.",
			status: on(doc.enable_manual_invoice_rate_feature),
			rollback: "گزینه «الزام ورود دستی نرخ تبدیل فاکتور» را خاموش کنید.",
			optional: 1,
		},
		{
			feature: "محافظ حذف شرکت و اسناد وابسته",
			owner_module: "حسابداری هوشمند",
			doctypes: "Transaction Deletion Record، شرکت، اسناد اختصاصی حسابداری، واسطه مالی",
			effect: "حذف شرکت یا اجرای Transaction Deletion Record وقتی سند اختصاصی یا واسطه مالی به آن شرکت وصل است متوقف می‌شود.",
			status: "فعال (محافظ الزامی)",
			rollback: "غیرفعال‌سازی از تنظیمات مجاز نیست. فقط با مجوز جداگانه و تغییر کنترل‌شده در اپ.",
			optional: 0,
		},
		{
			feature: "محافظ حذف اپ حسابداری",
			owner_module: "حسابداری هوشمند",
			doctypes: "تمام اسناد اختصاصی حسابداری",
			effect: "حذف اپ وقتی سند اختصاصی باقی مانده باشد متوقف می‌شود تا دفتر کل یتیم نشود.",
			status: "فعال (محافظ الزامی)",
			rollback: "غیرفعال‌سازی از تنظیمات مجاز نیست.",
			optional: 0,
		},
		{
			feature: "قفل آزمایشگاهی نویسنده استاندارد",
			owner_module: "حسابداری هوشمند",
			doctypes: "سند حسابداری هوشمند، پرداخت، سند حسابداری (فقط آزمایشگاه)",
			effect: "فقط روی سایت آزمایشگاهی و با پرچم جداگانه فعال می‌شود. روی این سایت زنده خاموش است.",
			status: "غیرفعال روی این سایت",
			rollback: "فعال‌سازی روی سایت زنده نیاز به تأیید جداگانه دارد. کلید خاموش‌کردن در تنظیمات وجود ندارد.",
			optional: 0,
		},
	];
}

function spRenderCrossAppImpact(frm) {
	const field = frm.fields_dict.cross_app_impact_html;
	if (!field) {
		return;
	}
	const rows = frappe.boot?.smartprocess_accounting?.cross_app_impacts?.length
		? frappe.boot.smartprocess_accounting.cross_app_impacts
		: spFallbackCrossAppImpacts(frm.doc || {});
	const body = rows
		.map((row) => {
			const optional = Number(row.optional);
			return `<tr>
				<td>${spEscape(row.feature)}</td>
				<td>${spEscape(row.owner_module)}</td>
				<td>${spEscape(row.doctypes)}</td>
				<td>${spEscape(row.effect)}</td>
				<td>${spEscape(row.status)}</td>
				<td>${spEscape(row.rollback)}</td>
				<td>${optional ? "اختیاری" : "محافظ الزامی"}</td>
			</tr>`;
		})
		.join("");
	field.$wrapper.html(`
		<div class="sp-cross-app-impact">
			<p>قابلیت‌های اختیاری از تب مربوط خاموش می‌شوند. محافظ‌های مالی و امنیتی فقط اطلاع‌رسانی هستند و کلید خاموش‌کردن ناامن ندارند.</p>
			<table class="table table-bordered">
				<thead>
					<tr>
						<th>قابلیت</th>
						<th>ماژول مالک</th>
						<th>اسناد تحت تأثیر</th>
						<th>اثر</th>
						<th>وضعیت</th>
						<th>بازگشت به رفتار استاندارد</th>
						<th>نوع</th>
					</tr>
				</thead>
				<tbody>${body}</tbody>
			</table>
		</div>
	`);
}

if (typeof frappe !== "undefined") {
	frappe.ui.form.on("SmartProcess Accounting Settings", {
		setup(frm) {
			// The table is absent until the site migrates; set_query would throw without it.
			if (!frm.fields_dict.default_accounts) {
				return;
			}
			frm.set_query("account", "default_accounts", (doc, cdt, cdn) => {
				const row = locals[cdt][cdn];
				const company = row.company && frappe.get_doc(":Company", row.company);
				return { filters: spDefaultAccountFilters(row, company && company.default_currency) };
			});
			// The Select control already uses the row DocType as context; the static grid cell does not.
			frappe.meta.docfield_map[SP_DEFAULT_ACCOUNT_ROW].account_purpose.formatter = spPurposeLabel;
			// The grid is already built here and renders its description only once, so fill its slot directly.
			const grid = frm.fields_dict.default_accounts.grid;
			grid.df.description = __("The account of related return invoices is taken from the original invoice.");
			grid.set_grid_description();
			$(grid.parent).find(".grid-description").show();
		},
		refresh(frm) {
			spRenderCrossAppImpact(frm);
		},
		after_save(frm) {
			spSyncBootFlags(frm.doc, frappe.boot);
			spRenderCrossAppImpact(frm);
		},
	});
}

if (typeof module === "object" && module.exports) {
	module.exports = { spDefaultAccountFilters, spSyncBootFlags, spRenderCrossAppImpact };
}
