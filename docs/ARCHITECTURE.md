# معماری MVP تبدیل

سند کاربری «تبدیل» یک DocType مستقل است. ERPNext Core همچنان تنها موتور دفتر کل است.

```text
UI سند تبدیل
        ↓
اعتبارسنجی و محاسبه مجدد سمت سرور
        ↓
AccountsController.get_gl_dict
        ↓
erpnext.accounts.general_ledger.make_gl_entries
        ↓
GL Entry / Payment Ledger Entry بومی
```

## نقش هر لایه

- **سند تبدیل**: فرم فارسی، دو طرف مستقل، ذخیره پیش‌نویس، Submit/Cancel.
- **conversion_math.py**: محاسبه مبلغ پایه، جهت، تراز، سازگاری ارز. بدون موتور دفتر کل.
- **AccountsController.get_gl_dict**: `voucher_type` و `voucher_no` را روی خود سند تبدیل می‌گذارد و فیلدهای مشترک GL را پر می‌کند.
- **make_gl_entries**: اعتبار دوره مالی، ابعاد، تراز، ساخت GL و در صورت نیاز PLE بومی.

## آنچه Core همچنان مرجع است

- طرح جدول `GL Entry` و `Payment Ledger Entry`
- تراز بدهکار/بستانکار
- ارز حساب در مقابل ارز تراکنش
- رفتار لغو و دفتر کل غیرقابل‌حذف
- مجوزها و چرخه سند Frappe

## آنچه این اپ انجام نمی‌دهد

- تغییر Core
- ساخت GL با SQL یا `frappe.get_doc("GL Entry")`
- تخصیص فاکتور و تسویه مانده فاکتور
- تغییر Payment Entry / Sales Invoice / Purchase Invoice
- واکشی خودکار نرخ ارز
