SELECT doctype, field, value
FROM tabSingles
WHERE doctype IN ('Accounts Settings','SmartProcess Accounting Settings','System Settings')
  AND field IN ('enable_immutable_ledger','delete_linked_ledger_entries','delete_linked_ledger','enable_v2_posting','pause_scheduler');

SELECT COUNT(*) AS gl_active FROM `tabGL Entry` WHERE is_cancelled=0;
SELECT COUNT(*) AS ple_active FROM `tabPayment Ledger Entry` WHERE delinked=0;
SELECT COUNT(*) AS open_si FROM `tabSales Invoice` WHERE docstatus=1 AND outstanding_amount!=0;
SELECT COUNT(*) AS fx_rows FROM `tabCurrency Exchange`;
SELECT name, stopped, frequency FROM `tabScheduled Job Type` WHERE method LIKE '%backup%';
SELECT COUNT(*) AS aging FROM `tabReport` WHERE name='Accounts Receivable';
