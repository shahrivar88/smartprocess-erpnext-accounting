# SmartProcess_ERPNext_Accounting

اپ Frappe/ERPNext برای رسید، پرداخت، تبدیل ارز و گردش حساب روی GL استاندارد. نسخه: **0.5.0**.

نیاز: Frappe `>=16,<17`، ERPNext `>=16,<17`، Python `>=3.10`.

وضعیت فعلی: [`docs/CURRENT.md`](docs/CURRENT.md). قراردادهای طراحی: [`docs/v2/`](docs/v2/BLUEPRINT.md).

## وضعیت عملیات

- **Receipt** و **Payment** مسیر ثبت فعال هستند. فرم سند جدید فقط همین دو گزینه را نشان می‌دهد.
- تبدیل ارز فعال DocType جداگانه `SmartProcess Receipt Conversion` است.
- تسویه اختیاری Path A: یک ردیف Customer یا Supplier در برابر بانک یا صندوق، یک `Payment Entry` استاندارد می‌سازد. حالت‌ها: Auto، Manual، Open.
- صفحه «تطبیق و تسویه» تخصیص پس از ثبت و Unreconcile را از مسیر استاندارد Payment Reconciliation انجام می‌دهد.
- تهاتر تک‌ارزی یک `Journal Entry` استاندارد بدون ردیف بانک می‌سازد.
- گزارش `Unallocatable Credits` اعتبارهای تاریخی بدون Payment Entry را فقط نمایش می‌دهد.
- چندردیفی و عملیات ناسازگار روی Path B (ثبت فعلی SmartProcess) می‌مانند.
- فلگ `enable_payment_entry_settlement` پیش‌فرض خاموش است.
- تهاتر Common Party: نرخ هر دو ردیف هم‌ارز از تنظیمات «منبع نرخ ارز تهاتر» می‌آید. پیش‌فرض نرخ فاکتور مبدأ است. JE دستی و تهاتر SmartProcess تغییر نمی‌کنند.
- **Transfer** و Currency Conversion روی سند حسابداری در Submit مسدودند و از انتخاب سند جدید مخفی‌اند. Schema برای اسناد تاریخی می‌ماند.
- هر Account فقط `account_currency` خودش را می‌پذیرد.
- DocTypeهای بازنشسته فقط Read+Report دارند؛ کنترلر آن‌ها throw می‌کند.
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

## تهاتر Common Party

مسیر: میز کار → حسابداری → تنظیمات حسابداری هوشمند → تب «نرخ ارز و تبدیل» → بخش «تهاتر طرف‌حساب مشترک».

| تنظیم | پیش‌فرض | رفتار |
|---|---|---|
| منبع نرخ ارز تهاتر | نرخ فاکتور مبدأ | هر دو ردیف هم‌ارز همان `conversion_rate` فاکتور را می‌گیرند. |
| منبع = جدول تبدیل ارز | — | نرخ از `Currency Exchange` تاریخ سند خوانده می‌شود. |
| منبع = رفتار استاندارد | — | هوک نرخ را عوض نمی‌کند. |
| نرخ مشترک برای حساب‌های هم‌ارز | روشن | اگر ارز هر دو حساب با ارز فاکتور یکی باشد، یک نرخ مشترک نوشته می‌شود. |
| توقف در صورت نبود نرخ معتبر | روشن | نرخ صفر یا نرخ ۱ برای فاکتور ارزی ثبت را متوقف می‌کند. |

سند حسابداری خودکار در `user_remark` منبع و نرخ را می‌نویسد. `ignore_exchange_rate` فقط بازنویسی نرخ همین سند را در `Journal Entry.validate` قطع می‌کند.

## محدودیت‌های باقی‌مانده

- رسید یا پرداخت چندردیفی هنوز چند `Payment Entry` در یک Submit نمی‌سازد.
- تهاتر چندارزی خاموش است. هر دو طرف باید شرکت، ارز و نرخ یکسان داشته باشند.
- Transfer هنوز پیاده‌سازی نشده است و از فرم سند جدید مخفی است.
- Override کلاس `Payment Entry` اضافه نشده است. مسیر اجرا همان Override موجود HRMS است.

## پشتیبان و حذف اپ

قبل از نصب یا migrate: `bench --site <site> backup --with-files`.

حذف فقط وقتی نگهبان `uninstall_guard` مانع نداشته باشد. DocType مجازی بدون جدول مانع حذف سایت خالی نیست. روی سایت دارای سند حسابداری، حذف متوقف می‌شود.

بازگردانی از بکاپ native Frappe است. روی سایت دورریختنی آزمایشگاه ایزوله یک بار restore پس از uninstall اثبات شد.

## پورت MariaDB (محلی، اعمال‌نشده)

انتشار فعلی `3306` از `finance-mgmt/overrides/compose.mariadb.yaml` است (`ports: - "3306:3306"`). فایل جایگزین محلی: [`deployment/compose.mariadb-localhost-only.yaml`](deployment/compose.mariadb-localhost-only.yaml). این overlay را به سرویس در حال اجرا اعمال نکنید مگر با تأیید جداگانه؛ append کردن فایل، publish روی `0.0.0.0` را نمی‌بندد.

## تست‌های Transfer

Submit عملیات Transfer و Currency Conversion روی رسید هوشمند مسدود است. تست‌های موتور ثبت آن عملیات‌ها حذف شدند؛ پوشش فعال در Receipt / Payment / `test_live_readiness.py` است.

## CI

`.github/workflows/hardening.yml` فقط قراردادهای بدون سایت را اجرا می‌کند (`compileall` + AST). تست کامل Frappe فقط در آزمایشگاه ایزوله است.
