SELECT name, currency, conversion_rate, docstatus, status
FROM `tabSales Invoice`
WHERE name='IN-260017';

SELECT default_currency
FROM `tabCompany`
WHERE name=(SELECT company FROM `tabSales Invoice` WHERE name='IN-260017');

SELECT COUNT(*) AS active_gl
FROM `tabGL Entry`
WHERE voucher_type='Sales Invoice' AND voucher_no='IN-260017' AND is_cancelled=0;

SELECT SUM(debit)=SUM(credit) AS gl_balanced
FROM `tabGL Entry`
WHERE voucher_type='Sales Invoice' AND voucher_no='IN-260017' AND is_cancelled=0;

SELECT COUNT(*) AS fx_usd_irr
FROM `tabCurrency Exchange`
WHERE (from_currency='USD' AND to_currency='IRR') OR (from_currency='IRR' AND to_currency='USD');
