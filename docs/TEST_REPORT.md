# گزارش تست MVP تبدیل

تاریخ اجرا: 2026-09-25

سایت: `SmartProcessERP`

هیچ سند مالی تولید Submit نشد.

## تست‌های automated

فرمان:

```bash
python -m unittest smartprocess_erpnext_accounting.smartprocess_accounting.doctype.smartprocess_currency_conversion.test_conversion_math -v
```

نتیجه: **16 تست، همه PASS**

| سناریو | نتیجه |
|--------|--------|
| Base → Base | PASS |
| USD → Base | PASS |
| Base → USD | PASS |
| USD → USD | PASS |
| USD → EUR مسدود | PASS |
| نرخ تبدیل صفر مسدود | PASS |
| مبلغ منفی مسدود | PASS |
| سند نامتراز مسدود | PASS |
| جهت نامعتبر مسدود | PASS |
| طرف حساب اجباریِ خالی مسدود | PASS |
| ناسازگاری نوع طرف حساب و حساب مسدود | PASS |
| نرخ دستی حفظ می‌شود | PASS |
| account_currency ≠ transaction_currency | PASS |
| NaN / Infinity مسدود | PASS |
| نقش‌های حسابداری native | PASS |
| جلوگیری از Submit تکراری | PASS، به‌عنوان مسئولیت چرخه سند Frappe مستند شد |

## تست‌هایی که عمداً اجرا نشدند

تست Submit واقعی برای ساخت GL روی `SmartProcessERP` اجرا نشد، چون نیاز به ثبت سند مالی تولید دارد.

Cancel واقعی، permission failure با کاربر زنده، و تخصیص فاکتور نیز در این مرحله اجرا نشدند.

## وضعیت داده پس از نصب

- سند تبدیل Submit‌شده: `0`
- `GL Entry`: `6` (بدون تغییر نسبت به forensic)
- `Journal Entry`: `2` (بدون تغییر نسبت به forensic)
