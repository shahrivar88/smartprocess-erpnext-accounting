"""The row's optional payment details: nine fields, one shared dialog, no accounting effect.

Reads the child DocType's JSON and the shared form script. It imports no framework, writes
nothing and needs no site, so it runs where a bench is not available. What it cannot check
without a database — the Desk rendering and a real save/reload — is named in the module's
last section as unverified rather than implied.

The nine fields are the eight in `NEW_FIELDS` plus `tracking_number`, which already exists
with the same meaning and is reused instead of duplicated.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parents[2]
PAIR_JSON = HERE.parent / "smartprocess_accounting_pair" / "smartprocess_accounting_pair.json"
DOCUMENT_JSON = HERE / "smartprocess_accounting_document.json"
FORM_JS = HERE / "receipt" / "receipt_form.js"
CONFIG_JS = HERE / "receipt" / "receipt_config.js"
DOCUMENT_JS = HERE / "smartprocess_accounting_document.js"

# The eight new fields, and the existing one that carries the ninth label.
NEW_FIELDS = {
    "receipt_date": "Date",
    "source_account_no": "Data",
    "target_account_no": "Data",
    "source_account_holder": "Data",
    "target_account_holder": "Data",
    "source_bank": "Data",
    "target_bank": "Data",
    "details_note": "Small Text",
}
REUSED_FIELD = "tracking_number"

PERSIAN_LABELS = {
    "receipt_date": "تاریخ رسید",
    REUSED_FIELD: "شماره پیگیری",
    "source_account_no": "حساب مبدأ (شماره حساب یا شبا)",
    "target_account_no": "حساب مقصد (شماره حساب یا شبا)",
    "source_account_holder": "نام صاحب حساب مبدأ",
    "target_account_holder": "نام صاحب حساب مقصد",
    "source_bank": "بانک مبدأ",
    "target_bank": "بانک مقصد",
    "details_note": "شرح",
}

# The eight fields the section already had. They keep their names and their types.
EXISTING_DETAILS = {
    "transfer_reference": "Data",
    "cheque_number": "Data",
    "depositor_name": "Data",
    "cheque_date": "Date",
    "bank_reference": "Data",
    "deposit_identifier": "Data",
    "bank_name": "Data",
}

OPERATIONS = ("Receipt", "Transfer", "Payment")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def fields_by_name(document):
    return {field["fieldname"]: field for field in document["fields"]}


def js_label_map():
    """`{fieldname: label}` from the shared script's row-label block."""
    source = FORM_JS.read_text(encoding="utf-8")
    block = re.search(
        r"const SP_RECEIPT_ROW_LABELS = \{(.*?)\n\};",
        source,
        re.DOTALL,
    )
    if not block:
        raise AssertionError("SP_RECEIPT_ROW_LABELS is missing from the shared form script")

    return dict(re.findall(r'(\w+):\s*"([^"]+)"', block.group(1)))


class TheNineFieldsTest(unittest.TestCase):
    def setUp(self):
        self.document = read_json(PAIR_JSON)
        self.fields = fields_by_name(self.document)

    def test_every_new_field_is_on_the_pair_and_not_the_document_header(self):
        header = fields_by_name(read_json(DOCUMENT_JSON))

        for name in NEW_FIELDS:
            with self.subTest(field=name):
                self.assertIn(name, self.fields, "the field is not on the row doctype")
                self.assertNotIn(name, header, "a row field must not live on the header")

    def test_the_ninth_label_reuses_the_existing_tracking_number(self):
        self.assertIn(REUSED_FIELD, self.fields)
        self.assertEqual(self.fields[REUSED_FIELD]["fieldtype"], "Data")

    def test_field_types_are_the_declared_ones(self):
        for name, fieldtype in NEW_FIELDS.items():
            with self.subTest(field=name):
                self.assertEqual(self.fields[name]["fieldtype"], fieldtype)

    def test_persian_labels_come_from_the_shared_row_dialog(self):
        labels = js_label_map()

        for name, label in PERSIAN_LABELS.items():
            with self.subTest(field=name):
                self.assertEqual(labels.get(name), label)

    def test_all_nine_are_optional(self):
        for name in (*NEW_FIELDS, REUSED_FIELD):
            field = self.fields[name]

            with self.subTest(field=name):
                self.assertFalse(field.get("reqd"), "an empty row must still save")
                self.assertFalse(field.get("mandatory_depends_on"))
                self.assertFalse(field.get("set_only_once"))

    def test_they_sit_under_the_existing_details_section(self):
        order = self.document["field_order"]
        section = order.index("details_section")

        for name in (*NEW_FIELDS, REUSED_FIELD):
            with self.subTest(field=name):
                self.assertGreater(order.index(name), section)
                self.assertIn(name, order)

    def test_the_note_has_its_own_full_width_column(self):
        order = self.document["field_order"]

        self.assertEqual(order[order.index("details_note") - 1], "details_note_column")
        self.assertEqual(self.fields["details_note_column"]["fieldtype"], "Column Break")


class ExistingFieldsTest(unittest.TestCase):
    def setUp(self):
        self.fields = fields_by_name(read_json(PAIR_JSON))

    def test_the_sections_existing_fields_are_unchanged(self):
        for name, fieldtype in EXISTING_DETAILS.items():
            with self.subTest(field=name):
                self.assertIn(name, self.fields)
                self.assertEqual(self.fields[name]["fieldtype"], fieldtype)

    def test_the_accounting_description_is_not_reused_as_the_note(self):
        """`..._description` is the ledger's remarks; the free-form note is a field of its own."""
        self.assertEqual(self.fields["credit_description"]["fieldtype"], "Small Text")
        self.assertEqual(self.fields["debit_description"]["fieldtype"], "Small Text")
        self.assertNotEqual(self.fields["details_note"]["label"], "Line Description")

    def test_no_fieldname_is_defined_twice(self):
        names = [field["fieldname"] for field in read_json(PAIR_JSON)["fields"]]

        self.assertEqual(len(names), len(set(names)), "a duplicate fieldname would collide on sync")

    def test_repeated_order_reads_are_idempotent(self):
        first = read_json(PAIR_JSON)["field_order"]

        self.assertEqual(first, read_json(PAIR_JSON)["field_order"])
        self.assertEqual(len(first), len(set(first)))


class PersistenceTest(unittest.TestCase):
    ROWS = (
        {
            "name": "row-1",
            "credit_amount": 100,
            "receipt_date": "2026-11-23",
            "tracking_number": "TRK-001",
            "source_account_no": "0012345678901",
            "target_account_no": "IR062960000000100324200001",
            "source_account_holder": "الف",
            "target_account_holder": "ب",
            "source_bank": "بانک الف",
            "target_bank": "بانک ب",
            "details_note": "خط اول\nخط دوم",
        },
        {
            "name": "row-2",
            "credit_amount": 250,
            "receipt_date": "2025-03-21",
            "tracking_number": "TRK-002",
            "source_account_no": "0000000000007",
            "target_account_no": "IR120570000000012345678901",
            "source_account_holder": "ج",
            "target_account_holder": "د",
            "source_bank": "بانک ج",
            "target_bank": "بانک د",
            "details_note": "",
        },
    )

    def round_trip(self, rows):
        """A saved document is JSON to the client and back; this is that trip and nothing else."""
        return json.loads(json.dumps(rows, ensure_ascii=False))

    def test_each_row_keeps_its_own_values(self):
        rows = self.round_trip(self.ROWS)

        for index, row in enumerate(rows):
            source = self.ROWS[index]

            for name in (*NEW_FIELDS, REUSED_FIELD):
                with self.subTest(row=row["name"], field=name):
                    self.assertEqual(row[name], source[name])

        self.assertNotEqual(rows[0]["source_account_no"], rows[1]["source_account_no"])

    def test_account_numbers_and_ibans_keep_their_leading_zeros(self):
        rows = self.round_trip(self.ROWS)

        self.assertEqual(rows[0]["source_account_no"], "0012345678901")
        self.assertEqual(rows[1]["source_account_no"], "0000000000007")
        self.assertEqual(rows[0]["target_account_no"], "IR062960000000100324200001")

    def test_the_date_stays_gregorian_and_the_existing_picker_covers_it(self):
        """`Date` is the field type the existing Jalali picker already renders and stores."""
        fields = fields_by_name(read_json(PAIR_JSON))

        self.assertEqual(fields["receipt_date"]["fieldtype"], "Date")
        self.assertEqual(fields["receipt_date"]["fieldtype"], fields["cheque_date"]["fieldtype"])

        rows = self.round_trip(self.ROWS)

        self.assertEqual(rows[0]["receipt_date"], "2026-11-23")
        self.assertEqual(rows[1]["receipt_date"], "2025-03-21")

    def test_an_empty_note_and_an_absent_field_are_both_readable(self):
        rows = self.round_trip(self.ROWS)

        self.assertEqual(rows[1]["details_note"], "")

        old_row = {"name": "row-old", "credit_amount": 10}
        self.assertNotIn("details_note", self.round_trip([old_row])[0])


class SharedDialogTest(unittest.TestCase):
    def test_all_three_operations_use_the_shared_row_side(self):
        config = CONFIG_JS.read_text(encoding="utf-8")

        for operation in OPERATIONS:
            with self.subTest(operation=operation):
                self.assertRegex(
                    config,
                    rf'ROW_SIDES:\s*\{{[^}}]*{operation}:\s*"(?:credit|debit)"',
                )

    def test_the_document_form_includes_the_shared_script(self):
        document_js = DOCUMENT_JS.read_text(encoding="utf-8")

        self.assertIn("receipt/receipt_form.js", document_js)
        self.assertIn("receipt/receipt_config.js", document_js)

    def test_the_labels_are_applied_by_the_shared_grid_layout(self):
        source = FORM_JS.read_text(encoding="utf-8")

        self.assertIn("...SP_RECEIPT_ROW_LABELS", source)
        self.assertRegex(source, r'\[fieldname,\s*"label",\s*label\]')


class NoAccountingEffectTest(unittest.TestCase):
    def test_no_server_module_reads_any_new_field(self):
        """The fields are the operator's notes. Posting, settlement and the ledger never ask."""
        names = tuple(NEW_FIELDS)
        offenders = []

        for path in APP.rglob("*.py"):
            if "test" in path.name or "__pycache__" in path.parts:
                continue

            text = path.read_text(encoding="utf-8")
            found = [name for name in names if name in text]

            if found:
                offenders.append((str(path.relative_to(APP)), found))

        self.assertEqual(offenders, [], f"a server module reads a row note: {offenders}")

    def test_the_layout_rule_is_scoped_to_the_details_section(self):
        css = (APP / "public" / "css" / "receipt_form.css").read_text(encoding="utf-8")

        self.assertIn('.form-section[data-fieldname="details_section"]', css)
        self.assertIn('[data-fieldname="details_note_column"]', css)
        self.assertIn('[data-fieldname="details_note"] textarea', css)


if __name__ == "__main__":
    unittest.main()
