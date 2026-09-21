"""Offline recovery and grounding checks, not a local-model accuracy benchmark."""
import copy
from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rasam_ai import ExtractionError, validate_invoice
from rasam_local_result import normalize_local_result


TEXT = 'Supplier: النور LLC\nInvoice: 00042-A/9\nDate: 2026-09-21\nNet 100.00\nVAT 15.00\nTotal 115.00 SAR'


def fixture():
    return {'supplier': 'النور LLC', 'invoiceNumber': '00042-A/9',
            'date': '2026-09-21', 'currency': 'SAR', 'net': '100.00',
            'vat': '15.00', 'total': '115.00', 'is_invoice': True,
            'warnings': [], 'field_warnings': [], 'line_items': []}


class LocalResultTests(unittest.TestCase):
    def test_valid_draft_is_unchanged_and_input_is_not_mutated(self):
        draft = fixture()
        before = copy.deepcopy(draft)
        result = normalize_local_result(draft, TEXT)
        self.assertEqual(result, draft)
        self.assertEqual(draft, before)
        self.assertIsNot(result, draft)

    def test_invalid_field_does_not_discard_valid_siblings(self):
        draft = fixture()
        draft.update(date='09/08/2026', net='1,234', currency='dirhams')
        result = normalize_local_result(draft, TEXT)
        self.assertEqual(result['supplier'], 'النور LLC')
        self.assertEqual(result['invoiceNumber'], '00042-A/9')
        self.assertEqual(result['total'], '115.00')
        self.assertEqual(result['vat'], '15.00')
        for field in ('date', 'net', 'currency'):
            self.assertIsNone(result[field])
            self.assertTrue(any(note['field'] == field for note in result['field_warnings']))

    def test_main_amounts_still_must_match_printed_numbers(self):
        draft = fixture()
        draft['total'] = '116.00'
        result = normalize_local_result(draft, TEXT)
        self.assertIsNone(result['total'])
        self.assertEqual(result['net'], '100.00')
        self.assertTrue(any('printed number' in note['message'] for note in result['field_warnings']))

    def test_exact_json_numbers_preserve_precision_and_strings(self):
        draft = fixture()
        draft.update(net=100, vat=15.0, total=Decimal('115.000000000000000001'))
        result = normalize_local_result(draft, TEXT + '\n115.000000000000000001')
        self.assertEqual(result['net'], '100')
        self.assertEqual(result['vat'], '15.0')
        self.assertEqual(result['total'], '115.000000000000000001')

    def test_numeric_decimal_exponents_expand_without_rounding(self):
        draft = fixture()
        draft['net'] = Decimal('1E+2')
        self.assertEqual(normalize_local_result(draft, TEXT)['net'], '100')
        draft['net'] = '1E+2'
        self.assertIsNone(normalize_local_result(draft, TEXT)['net'])

    def test_negative_and_zero_amounts_are_not_clamped_or_invented(self):
        draft = fixture()
        draft.update(net='-100.00', vat=0, total=Decimal('-100.00'))
        result = normalize_local_result(draft, 'Credit note\nNet -100.00\nVAT 0\nTotal -100.00')
        self.assertEqual((result['net'], result['vat'], result['total']), ('-100.00', '0', '-100.00'))

    def test_booleans_nonfinite_and_complex_money_are_cleared(self):
        for value in (True, False, float('inf'), float('nan'), Decimal('NaN'),
                      Decimal('Infinity'), Decimal('1E+1000000'), Decimal('1E-1000000'),
                      {}, [], 'NaN', '1,234', '1 000.00', '12,34.56'):
            with self.subTest(value=repr(value)):
                draft = fixture()
                draft['net'] = value
                result = normalize_local_result(draft, TEXT)
                self.assertIsNone(result['net'])
                self.assertEqual(result['total'], '115.00')

    def test_arabic_digits_and_unambiguous_arabic_separators(self):
        draft = fixture()
        draft.update(net=' ١٬٢٣٤٫٥٠ ', vat='۱۵٫۰۰', total='١٢٤٩.٥٠')
        result = normalize_local_result(draft, 'Net ١٬٢٣٤٫٥٠\nVAT ۱۵٫۰۰\nTotal ١٢٤٩.٥٠')
        self.assertEqual((result['net'], result['vat'], result['total']), ('1234.50', '15.00', '1249.50'))
        for value in ('١٢٬٣٤', '١٬٢٣٤,٥٠', '1٫23٫4'):
            draft['net'] = value
            self.assertIsNone(normalize_local_result(draft, TEXT)['net'])

    def test_explicit_amount_formatting_is_normalized_without_inference(self):
        draft = fixture()
        draft.update(net='SAR 1,950.00', vat='15,00', total='1.965,00', currency=None)
        result = normalize_local_result(draft, 'Net SAR 1,950.00\nVAT 15,00\nTotal 1.965,00')
        self.assertEqual((result['net'], result['vat'], result['total']), ('1950.00', '15.00', '1965.00'))
        self.assertIsNone(result['currency'])
        draft['net'] = '(100.00)'
        self.assertEqual(normalize_local_result(draft, 'Credit -100.00')['net'], '-100.00')

    def test_explicit_dates_normalize_but_ambiguous_dates_stay_empty(self):
        draft = fixture()
        for raw, expected in (('12 August 2026', '2026-08-12'),
                              ('25/08/2026', '2026-08-25'),
                              ('2026/8/25', '2026-08-25'),
                              ('٢٥ أغسطس ٢٠٢٦', '2026-08-25'),
                              ('08/09/2026', None), ('25/08/26', None),
                              ('12 August 26', None), ('30 February 2026', None)):
            with self.subTest(raw=raw):
                draft['date'] = raw
                self.assertEqual(normalize_local_result(draft, TEXT)['date'], expected)

    def test_missing_main_fields_are_null_with_notes(self):
        result = normalize_local_result({'is_invoice': True, 'supplier': 'Seller'}, TEXT)
        self.assertEqual(result['supplier'], 'Seller')
        self.assertIsNone(result['net'])
        self.assertEqual(len(result['field_warnings']), 6)
        self.assertEqual(result['line_items'], [])
        validate_invoice(result)

    def test_null_like_values_and_numeric_identifiers_are_not_invented(self):
        draft = fixture()
        draft.update(supplier='   ', invoiceNumber=42, net='null', vat='N/A', total=None)
        result = normalize_local_result(draft, TEXT)
        for field in ('supplier', 'invoiceNumber', 'net', 'vat', 'total'):
            self.assertIsNone(result[field])
        self.assertEqual(len(result['field_warnings']), 4)

    def test_calendar_date_and_supported_currency_are_checked(self):
        draft = fixture()
        draft.update(date='2026-02-30', currency=' aed ', supplier=' النور LLC ')
        result = normalize_local_result(draft, TEXT)
        self.assertIsNone(result['date'])
        self.assertEqual(result['currency'], 'AED')
        self.assertEqual(result['supplier'], 'النور LLC')

    def test_bad_ancillary_notes_do_not_discard_fields(self):
        draft = fixture()
        draft['warnings'] = [' Keep this. ', {}, '', 'x' * 1001]
        draft['field_warnings'] = [{'field': 'supplier', 'message': ' Verify seller. '},
                                   {'field': [], 'message': 'bad'},
                                   {'field': 'unknown', 'message': 'bad'}]
        result = normalize_local_result(draft, TEXT)
        self.assertEqual(result['total'], '115.00')
        self.assertIn('Keep this.', result['warnings'])
        self.assertIn({'field': 'supplier', 'message': 'Verify seller.'}, result['field_warnings'])
        validate_invoice(result)

    def test_invalid_ancillary_types_are_empty_with_notes(self):
        draft = fixture()
        draft.update(warnings={}, field_warnings='none', line_items=None)
        result = normalize_local_result(draft, TEXT)
        self.assertEqual(result['net'], '100.00')
        self.assertEqual(result['line_items'], [])
        self.assertEqual(result['field_warnings'], [])
        self.assertEqual(len(result['warnings']), 3)

    def test_line_items_retain_valid_values_drop_bad_entries_clear_bad_numbers(self):
        draft = fixture()
        draft['line_items'] = [
            {'description': ' قلم ', 'quantity': 2, 'unit_price': '50.00', 'net_amount': True},
            {'description': 'Paper'},
            {'description': '', 'quantity': None},
            {'description': 'Unknown', 'alias': '5'},
            'not an item',
        ]
        result = normalize_local_result(draft, TEXT)
        self.assertEqual(result['line_items'], [
            {'description': 'قلم', 'quantity': '2', 'unit_price': '50.00', 'net_amount': None},
            {'description': 'Paper', 'quantity': None, 'unit_price': None, 'net_amount': None},
        ])
        self.assertEqual(result['total'], '115.00')

    def test_arrays_and_strings_are_bounded_without_truncating_values(self):
        draft = fixture()
        draft['supplier'] = 'x' * 1001
        draft['warnings'] = ['Review'] * 100
        draft['field_warnings'] = [{'field': 'net', 'message': 'Review'}] * 100
        draft['line_items'] = [{'description': 'Item', 'quantity': '1',
                                'unit_price': None, 'net_amount': None}] * 100
        draft['total'] = '999'
        result = normalize_local_result(draft, TEXT)
        self.assertIsNone(result['supplier'])
        self.assertIsNone(result['total'])
        self.assertEqual(len(result['line_items']), 50)
        self.assertLessEqual(len(result['warnings']), 30)
        self.assertLessEqual(len(result['field_warnings']), 30)
        self.assertTrue(any(note['field'] == 'supplier' for note in result['field_warnings']))
        self.assertTrue(any(note['field'] == 'total' for note in result['field_warnings']))
        validate_invoice(result)

    def test_noninvoice_is_all_null_and_has_explanation(self):
        draft = fixture()
        draft['is_invoice'] = False
        draft['line_items'] = [{'description': 'Item', 'quantity': '1', 'unit_price': None, 'net_amount': None}]
        result = normalize_local_result(draft, TEXT)
        for field in ('supplier', 'invoiceNumber', 'date', 'currency', 'net', 'vat', 'total'):
            self.assertIsNone(result[field])
        self.assertEqual(result['line_items'], [])
        self.assertTrue(result['warnings'])

    def test_rejects_aliases_wrappers_and_missing_or_coerced_identity(self):
        for draft in (None, [], {'invoice': fixture()}, {'is_invoice': 'true'},
                      {'is_invoice': 1}, {'supplier': 'Seller'},
                      dict(fixture(), vendor='Seller'), dict(fixture(), total_amount='115')):
            with self.subTest(draft=draft):
                with self.assertRaises(ExtractionError) as caught:
                    normalize_local_result(draft, TEXT)
                self.assertEqual(caught.exception.code, 'invalid_response')

    def test_original_validator_is_still_strict(self):
        draft = fixture()
        draft['total'] = 115
        with self.assertRaises(ExtractionError):
            validate_invoice(draft)


if __name__ == '__main__':
    unittest.main()
