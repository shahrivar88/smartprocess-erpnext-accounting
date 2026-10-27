# Changelog

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
