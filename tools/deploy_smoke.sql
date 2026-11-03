SELECT name FROM `tabModule Def` WHERE app_name='smartprocess_erpnext_accounting';
SELECT name FROM `tabDocType` WHERE module='SmartProcess Accounting' ORDER BY name;
SELECT field, value FROM tabSingles WHERE doctype='SmartProcess Accounting Settings' AND field IN ('enable_v2_posting','enable_live_number_separator');
SELECT name FROM `tabInstalled Application` WHERE app_name='smartprocess_erpnext_accounting';
SELECT app_name, app_version FROM `tabInstalled Application` ORDER BY app_name;
SELECT COUNT(*) AS documents FROM `tabSmartProcess Accounting Document`;
SELECT COUNT(*) AS postings FROM `tabSmartProcess Accounting Posting`;
SELECT COUNT(*) AS conversions FROM `tabSmartProcess Receipt Conversion`;
SELECT name FROM `tabParty Type` WHERE name='Financial Intermediary';
