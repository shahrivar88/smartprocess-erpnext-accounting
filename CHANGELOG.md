# Changelog

## 0.4.0

- Path A: یک ردیف Customer یا Supplier در برابر بانک یا صندوق با یک `Payment Entry` استاندارد ثبت می‌شود.
- حالت‌های Auto، Manual و Open روی همان Payment Entry می‌مانند.
- صفحه «تطبیق و تسویه» تخصیص پس از ثبت و Unreconcile را از Payment Reconciliation استاندارد انجام می‌دهد.
- تهاتر تک‌ارزی یک `Journal Entry` استاندارد بدون بانک می‌سازد.
- گزارش `Unallocatable Credits` اعتبار تاریخی بدون Payment Entry را بدون تغییر سند نشان می‌دهد.
- چندردیفی روی Path B می‌ماند تا اتمیک بودن چند Payment Entry در یک Submit ثابت شود.
- Cancel مسیر Path A لینک سند مادر به Payment Entry را نگه می‌دارد.
- فلگ `enable_payment_entry_settlement` پیش‌فرض خاموش است.

## 0.3.0

- Receipt و Payment مسیر ثبت فعال؛ Transfer و Currency Conversion در Submit مسدود.
- نمایش نرخ بومی روی Quotation / Sales Order / Purchase Order (فقط نمایش) و ویرایش کنترل‌شده روی Sales Invoice / Purchase Invoice / Payment Entry.
- قفل حذف شرکت از مسیر Transaction Deletion Record؛ Hybrid Lock فقط در آزمایشگاه ایزوله.
- Settings با `track_changes` استاندارد؛ DocTypeهای بازنشسته Read+Report.
- نگهبان uninstall قبل از حذف اپ.
- تست‌های موتور Transfer از discovery خارج و در `archived_v2_posting.py` بایگانی شدند.
- APIهای `frappe.call` / `frappe.xcall` روش HTTP صریح دارند: Link query و چند خوانندهٔ فرم `GET`، بقیه `POST`.
- overlay محلی برای بستن publish عمومی `3306` در `deployment/compose.mariadb-localhost-only.yaml` (اعمال‌نشده).
- CI بدون سایت: `.github/workflows/hardening.yml`.
- نگهبان uninstall دیگر DocType مجازی بدون جدول را مانع حذف یک سایت خالی حساب نمی‌کند.

## 0.2.0

- حساب‌های پیش‌فرض مرکزی برای فاکتور فروش و خرید.
- Financial Intermediary به‌عنوان party کامل ERPNext.
