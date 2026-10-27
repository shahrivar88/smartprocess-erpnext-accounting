# SmartProcess_ERPNext_Accounting

اپ Frappe/ERPNext برای رسید، پرداخت و نمایش نرخ ارز بومی. نسخهٔ هدف: **0.3.0**.

نیاز: Frappe `>=16,<17`، ERPNext `>=16,<17`، Python `>=3.10`.

معماری V2 در [`docs/v2/BLUEPRINT.md`](docs/v2/BLUEPRINT.md).

## وضعیت عملیات

- **Receipt** و **Payment** مسیر ثبت فعال هستند.
- **Transfer** و **Currency Conversion** در Submit مسدودند.
- DocTypeهای بازنشسته فقط Read+Report دارند؛ کنترلر آن‌ها هنوز throw می‌کند.
- Hybrid Lock در کد تولید خاموش است (`LIVE_LOCKS_ENABLED = False`).
- `ignore_permissions` و `allow_guest` در کد تولید وجود ندارد.

## نصب روی Ubuntu / Bench موجود

فقط روی سایتی که از قبل Frappe+ERPNext 16 دارد. Bench یا کانتینر جدید نسازید مگر آزمایشگاه ایزوله.

1. بکاپ native سایت (`bench --site <site> backup --with-files`).
2. اپ را در `apps/` قرار دهید و `bench setup requirements` را اجرا کنید.
3. نصب و migrate:

```bash
bench --site <site> install-app smartprocess_erpnext_accounting
bench --site <site> migrate
bench --site <site> clear-cache
bench --site <site> clear-website-cache
```

4. دارایی‌ها: `bench build --app smartprocess_erpnext_accounting` در صورت نیاز.
5. نقش‌ها: Accounts User / Accounts Manager / Auditor استاندارد ERPNext. Role سفارشی ساخته نمی‌شود.
6. تنظیم `sp_lab_hybrid_lock` را روی سایت مشترک یا Ubuntu اصلی نگذارید.

سایت توسعهٔ فعلی `SmartProcessERP` روی پورت `8080` تا migrate تأییدشده، فقط نمایش است.

## ورود

1. Desk → «رسید هوشمند».
2. سند `SmartProcess Accounting Document` با نوع Receipt یا Payment.

## محدودیت‌های باقی‌مانده

- تخصیص رسید به فاکتور و تسویهٔ Outstanding فاکتور در این نسخه کامل نیست.
- Transfer / Currency Conversion هنوز پیاده‌سازی نشده‌اند.
- سایت مشترک `8080` ممکن است JSONهای جدید (از جمله `track_changes`) را migrate نکرده باشد.

## پشتیبان و حذف اپ

قبل از نصب یا migrate: `bench --site <site> backup --with-files`.

حذف فقط وقتی نگهبان `uninstall_guard` مانع نداشته باشد. DocType مجازی بدون جدول مانع حذف سایت خالی نیست. روی سایت دارای سند حسابداری، حذف متوقف می‌شود.

بازگردانی از بکاپ native Frappe است. روی سایت دورریختنی آزمایشگاه ایزوله یک بار restore پس از uninstall اثبات شد.

## پورت MariaDB (محلی، اعمال‌نشده)

انتشار فعلی `3306` از `finance-mgmt/overrides/compose.mariadb.yaml` است (`ports: - "3306:3306"`). فایل جایگزین محلی: [`deployment/compose.mariadb-localhost-only.yaml`](deployment/compose.mariadb-localhost-only.yaml). این overlay را به سرویس در حال اجرا اعمال نکنید مگر با تأیید جداگانه؛ append کردن فایل، publish روی `0.0.0.0` را نمی‌بندد.

## تست‌های بایگانی‌شده

`archived_v2_posting.py` و پنج تست دقت Transfer از `test_live_readiness.py` از discovery خارج شده‌اند چون Submit آن عملیات‌ها مسدود است. کاهش Skip به‌تنهایی افزایش پوشش نیست؛ پوشش جدید از تست‌های Receipt / Payment / live_readiness است.

## CI

`.github/workflows/hardening.yml` فقط قراردادهای بدون سایت را اجرا می‌کند (`compileall` + AST). تست کامل Frappe فقط در آزمایشگاه ایزوله است.
