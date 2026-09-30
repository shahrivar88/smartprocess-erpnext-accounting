# تحلیل Forensic حسابداری ERPNext 16.35.0

> **Legacy V1 / historical reference.** Environment facts in this document are not the V2 runtime contract.

این سند خلاصهٔ همان بررسی خواندنی تأییدشده است. تحلیل از صفر تکرار نشده است.

## محیط مشاهده‌شده

| مورد | مقدار |
|------|--------|
| پروژه Compose | `erpnext` در `C:\Users\shahr\finance-mgmt` |
| سایت تولید | `SmartProcessERP` |
| Frontend | پورت `8080` |
| ERPNext | `16.35.0` |
| Frappe | `16.34.0` |
| شرکت | `پردازش هوشمند` |
| ارز پایه شرکت | از `Company.default_currency` خوانده می‌شود؛ در این سایت `IRR` است و نباید در کد سخت شود |

اپ‌های نصب‌شده در زمان بررسی: `frappe`, `erpnext`, `jalali_shamsi_datepicker`, `smartprocee_erpnext_persiant`, `smartprocee_erpnext_homepage`, `whatsapp`, `smartprocee_erpnext_telegram`.

سایت `jalali_ui_test` روی دیسک وجود دارد ولی منبع این اپ نیست. کانتینرهای پورت `8001` هم استفاده نشده‌اند.

## سند حسابداری مرجع برای «تبدیل»

سند کاربری باید DocType مستقل باشد، نه تغییر Payment Entry.

دلیل:

- Payment Entry یک طرف حساب و الگوی `paid_from` / `paid_to` دارد.
- Journal Entry الگوی دوطرفه و چندارزی نزدیک‌تری دارد، ولی ساخت JE واسط `voucher_type` را از «تبدیل» جدا می‌کند.
- `AccountsController.get_gl_dict` مقدار `voucher_type=self.doctype` و `voucher_no=self.name` را می‌گذارد.

بنابراین سند مرجع کاربری «تبدیل» است و الگوی پیاده‌سازی posting از Journal Entry گرفته می‌شود.

## API بومی ثبت

Submit:

1. `build_gl_map()`
2. `self.get_gl_dict(row)`
3. `erpnext.accounts.general_ledger.make_gl_entries(...)`

Cancel:

1. `ignore_linked_doctypes` شامل `GL Entry` و `Payment Ledger Entry`
2. `make_gl_entries(cancel=1)`
3. `make_reverse_gl_entries` در Core

اگر دفتر کل immutable روشن باشد، ردیف تاریخی حذف نمی‌شود و ردیف معکوس درج می‌شود.

## فیلدهای واقعی تأییدشده

### GL Entry

`account`, `account_currency`, `transaction_currency`, `transaction_exchange_rate`, `debit`, `credit`, `debit_in_account_currency`, `credit_in_account_currency`, `debit_in_transaction_currency`, `credit_in_transaction_currency`, `party_type`, `party`, `against_voucher_type`, `against_voucher`, `voucher_type`, `voucher_no`, `remarks`, `company`, `posting_date`, `fiscal_year`

### Payment Entry

`paid_from`, `paid_to`, `paid_from_account_currency`, `paid_to_account_currency`, `source_exchange_rate`, `target_exchange_rate`, `paid_amount`, `received_amount`, `difference_amount`, `references`

### Journal Entry Account

`account`, `account_currency`, `exchange_rate`, `debit`, `credit`, `debit_in_account_currency`, `credit_in_account_currency`, `party_type`, `party`, `reference_type`, `reference_name`

### Payment Ledger Entry

`amount`, `amount_in_account_currency`, `account_currency`, `against_voucher_no`  
ابعاد `transaction_currency` در PLE وجود ندارد.

## بقای ارز تراکنش

در دادهٔ موجود، سند `ACC-JV-2026-00002` نشان داد:

- یک ردیف: `account_currency=IRR` و `transaction_currency=USD`
- ردیف دیگر: `account_currency=USD` و `transaction_currency=USD`
- نرخ تراکنش سند: `100000000`

هر voucher در مسیر native عملاً یک `transaction_currency` دارد. JE اولین ارز خارجی را به کل سند می‌دهد.

`get_gl_dict` برای DocType سفارشی، `transaction_currency` را از `self.currency` و نرخ را از `conversion_rate` / آرگومان می‌گیرد. به‌همین دلیل سند تبدیل این دو فیلد پنهان را دارد.

## دادهٔ تولید در زمان بررسی

| نمونه درخواستی | وضعیت |
|----------------|--------|
| فاکتور فروش IRR | موجود نبود |
| فاکتور فروش USD روی حساب دریافتنی IRR | موجود نبود |
| Payment Entry | موجود نبود |
| GL چندارزی | موجود بود: `ACC-JV-2026-00002` |
| سند لغوشده | موجود بود: `ACC-JV-2026-00001` |

هیچ سند مالی برای «دیدن نتیجه» ساخته یا Submit نشد.

## تخصیص فاکتور

تسویه صحیح فاکتور در ERPNext 16.35 از طریق `against_voucher` و Payment Ledger Entry است. این کار در MVP پیاده نشده است تا مانده فاکتور به‌اشتباه صفر نشود.

## محدودیت‌هایی که بدون تغییر Core حل نمی‌شوند

- دو `transaction_currency` مستقل در یک سند، مثل USD→EUR
- تحمیل نرخ دستی در حالی که Core برای برخی DocTypeها نرخ را از مرجع می‌آورد؛ به‌همین دلیل از Payment Entry استفاده نشده است
- PLE فقط ارز حساب و ارز شرکت را نگه می‌دارد، نه ارز تراکنش
