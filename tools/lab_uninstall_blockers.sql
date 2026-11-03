SELECT 'SmartProcess Accounting Document' AS doctype, COUNT(*) AS n FROM `tabSmartProcess Accounting Document`
UNION ALL SELECT 'SmartProcess Accounting Posting', COUNT(*) FROM `tabSmartProcess Accounting Posting`
UNION ALL SELECT 'SmartProcess Receipt Conversion', COUNT(*) FROM `tabSmartProcess Receipt Conversion`
UNION ALL SELECT 'SmartProcess Currency Conversion', COUNT(*) FROM `tabSmartProcess Currency Conversion`
UNION ALL SELECT 'SmartProcess Financial Intermediary', COUNT(*) FROM `tabSmartProcess Financial Intermediary`
UNION ALL SELECT 'Party Type leftover', COUNT(*) FROM `tabParty Type` WHERE name='Financial Intermediary';
