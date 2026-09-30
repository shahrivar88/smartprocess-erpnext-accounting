# SmartProcess_ERPNext_Accounting

> **Legacy V1 / historical reference.** V2 architecture is defined in [`docs/v2/BLUEPRINT.md`](docs/v2/BLUEPRINT.md).

اپ مستقل Frappe/ERPNext برای گردش حسابداری «تبدیل».

نسخه فعلی یک MVP است: سند دوطرفه، ارز دستی، ثبت دفتر کل از مسیر native ERPNext، و لغو استاندارد.

## محدودیت مهم نسخه اولیه

**تخصیص تبدیل به فاکتور و تسویه مانده فاکتور در نسخه اولیه پیاده‌سازی نشده است.**

این نسخه فقط موارد زیر را اثبات می‌کند:

- ثبت دوطرفه
- طرف حساب
- داده چندارزی تراکنش
- GL بومی ERPNext
- لغو سند

## نصب

فقط روی سایت موجود `SmartProcessERP` نصب شود. سایت، Bench، کانتینر یا پورت جدید ساخته نشود.

پس از بکاپ کامل native:

```bash
bench --site SmartProcessERP install-app smartprocess_erpnext_accounting
bench --site SmartProcessERP clear-cache
```

## ورود به سند

1. وارد ERPNext روی پورت `8080` شوید.
2. میز کار «حسابداری اسمارت پروسس» را باز کنید.
3. میانبر «تبدیل» را انتخاب کنید.

از نوار جستجو هم می‌توان «تبدیل» یا `SmartProcess Currency Conversion` را جستجو کرد.

## قوانین MVP

- نرخ تبدیل را کاربر دستی وارد می‌کند.
- نرخ از اینترنت یا Currency Exchange واکشی نمی‌شود.
- هر سند فقط یک `transaction_currency` دارد.
- دو ارز خارجی متفاوت در یک سند (مثل USD و EUR) مسدود است.
- حساب معین را کاربر انتخاب می‌کند؛ پیش‌فرض مشتری/تأمین‌کننده تحمیل نمی‌شود.
- ثبت حسابداری فقط از `AccountsController.get_gl_dict` و `erpnext.accounts.general_ledger.make_gl_entries` انجام می‌شود.
