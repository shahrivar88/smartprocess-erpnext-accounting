SELECT COUNT(*) AS gl_party_without_ple
FROM `tabGL Entry` gl
WHERE gl.is_cancelled=0
  AND IFNULL(gl.party,'')!=''
  AND NOT EXISTS (
    SELECT 1 FROM `tabPayment Ledger Entry` ple
    WHERE ple.delinked=0
      AND ple.voucher_type=gl.voucher_type
      AND ple.voucher_no=gl.voucher_no
      AND ple.account=gl.account
      AND IFNULL(ple.party,'')=IFNULL(gl.party,'')
  );

SELECT COUNT(*) AS ple_without_active_gl
FROM `tabPayment Ledger Entry` ple
WHERE ple.delinked=0
  AND NOT EXISTS (
    SELECT 1 FROM `tabGL Entry` gl
    WHERE gl.is_cancelled=0
      AND gl.voucher_type=ple.voucher_type
      AND gl.voucher_no=ple.voucher_no
      AND gl.account=ple.account
  );
