SELECT doctype, field, value
FROM tabSingles
WHERE doctype IN ('Accounts Settings','System Settings')
  AND field IN ('enable_immutable_ledger','delete_linked_ledger_entries','delete_linked_ledger','pause_scheduler');
