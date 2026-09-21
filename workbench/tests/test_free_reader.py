"""Offline contracts for local OCR routing and optional Groq text extraction."""
import base64
from contextlib import contextmanager
from decimal import Decimal
import http.client
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from urllib import error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rasam_ai import ExtractionError, MAX_RESPONSE_BYTES
from rasam_groq import (DEFAULT_GROQ_MODEL, GROQ_URL, MAX_GROQ_TEXT,
                        GroqTextExtractor, validate_text_result)
from start_rasam import create_server


OCR_TEXT = '''Tax Invoice
Supplier: Al Noor Stationery
Invoice Number: R-00042
Date: 2026-09-21
Currency: SAR
Net Amount: 100.00
VAT Amount: 15.00
Grand Total: 115.00
'''
OCR_STATUS = {'available': True, 'engine': 'test-local-engine',
              'languages': ['eng'], 'message': 'A local test reader is available.'}


def invoice_fixture():
    return {'supplier': 'Al Noor Stationery', 'invoiceNumber': 'R-00042',
            'date': '2026-09-21', 'currency': 'SAR', 'net': '100.00',
            'vat': '15.00', 'total': '115.00', 'is_invoice': True,
            'vatRate': None, 'supplierVatNumber': None,
            'warnings': [], 'field_warnings': [], 'line_items': []}


def upload_fixture():
    return {'filename': 'invoice.pdf', 'mime_type': 'application/pdf',
            'data_base64': base64.b64encode(b'%PDF-1.7\nTest document').decode('ascii')}


def groq_response(invoice=None):
    return {'choices': [{'finish_reason': 'stop', 'message': {
        'role': 'assistant', 'content': json.dumps(invoice or invoice_fixture())}}]}


class GroqContractTests(unittest.TestCase):
    def extractor_for(self, response):
        def opener(req, timeout):
            return io.BytesIO(json.dumps(response).encode('utf-8'))
        return GroqTextExtractor('fake-test-key', opener=opener)

    def test_wire_request_sends_only_ocr_text_and_uses_json_mode(self):
        requests = []

        def opener(req, timeout):
            requests.append((req, timeout))
            return io.BytesIO(json.dumps(groq_response()).encode('utf-8'))

        result = GroqTextExtractor('fake-test-key', opener=opener)(OCR_TEXT)
        self.assertEqual(result, invoice_fixture())
        req, timeout = requests[0]
        self.assertEqual(len(requests), 1)
        self.assertEqual(req.full_url, GROQ_URL)
        self.assertEqual(req.get_method(), 'POST')
        self.assertEqual(req.get_header('Authorization'), 'Bearer fake-test-key')
        self.assertEqual(timeout, 90)
        body = json.loads(req.data)
        self.assertEqual(body['model'], DEFAULT_GROQ_MODEL)
        self.assertEqual(body['response_format'], {'type': 'json_object'})
        self.assertEqual(body['reasoning_effort'], 'none')
        self.assertIs(body['stream'], False)
        self.assertIn(OCR_TEXT, body['messages'][1]['content'])
        self.assertTrue(all(isinstance(message['content'], str) for message in body['messages']))
        self.assertIn('untrusted document data', body['messages'][0]['content'])
        self.assertNotIn('fake-test-key', req.data.decode('utf-8'))
        self.assertNotIn('data_base64', body['messages'][1]['content'])
        self.assertNotIn('image_url', body)
        self.assertNotIn('tools', body)

    def test_empty_or_excessive_text_never_reaches_network(self):
        calls = []
        reader = GroqTextExtractor('fake-test-key', opener=lambda *a, **k: calls.append(a))
        for text, expected in (('', 'empty_ocr'), ('  \n ', 'empty_ocr'),
                               (None, 'empty_ocr'), ('x' * (MAX_GROQ_TEXT + 1), 'text_too_long')):
            with self.subTest(expected=expected, text_type=type(text).__name__):
                with self.assertRaises(ExtractionError) as caught:
                    reader(text)
                self.assertEqual(caught.exception.code, expected)
        self.assertEqual(calls, [])

    def test_unprinted_amounts_are_cleared_instead_of_calculated(self):
        invoice = invoice_fixture()
        invoice['vat'] = '15.00'
        invoice['total'] = '115.00'
        text = 'Invoice\nNet amount: SAR 100.00\nVAT rate: 15%'
        result = validate_text_result(invoice, text)
        self.assertEqual(result['net'], '100.00')
        self.assertIsNone(result['vat'])
        self.assertIsNone(result['total'])
        self.assertEqual({warning['field'] for warning in result['field_warnings']}, {'vat', 'total'})

    def test_printed_arabic_digits_and_signed_credit_values_are_preserved(self):
        invoice = invoice_fixture()
        invoice.update(net='1950.00', vat=None, total='-2223.00')
        result = validate_text_result(invoice, 'صافي ١٬٩٥٠٫٠٠\nالإجمالي -٢٬٢٢٣٫٠٠')
        self.assertEqual(result['net'], '1950.00')
        self.assertEqual(result['total'], '-2223.00')
        self.assertIsNone(result['vat'])
        self.assertEqual(result['field_warnings'], [])

    def test_schema_validation_rejects_unknown_fields_and_unsupported_currency(self):
        for change in ({'invented': 'extra field'}, {'currency': 'KWD'}, {'total': 'NaN'}):
            with self.subTest(change=change):
                example = invoice_fixture()
                example.update(change)
                with self.assertRaises(ExtractionError) as caught:
                    self.extractor_for(groq_response(example))(OCR_TEXT)
                self.assertEqual(caught.exception.code, 'invalid_response')

    def test_text_ai_tax_fields_require_source_evidence_and_seller_identity(self):
        invoice = invoice_fixture()
        invoice.update(vatRate='5', supplierVatNumber='001234567890001')
        source = OCR_TEXT + '\nVAT rate: ٥٪\nSupplier TRN: ٠٠١٢٣٤٥٦٧٨٩٠٠٠١'
        result = self.extractor_for(groq_response(invoice))(source)
        self.assertEqual(result['vatRate'], '5')
        self.assertEqual(result['supplierVatNumber'], '001234567890001')
        source = OCR_TEXT + '\nDiscount: 5%\nCustomer TRN: 001234567890001'
        result = self.extractor_for(groq_response(invoice))(source)
        self.assertIsNone(result['vatRate'])
        self.assertIsNone(result['supplierVatNumber'])
        self.assertEqual(result['total'], '115.00')

    def test_missing_or_malformed_upstream_structures_fail_safely(self):
        cases = [None, [], {}, {'choices': []}, {'choices': ['unexpected']},
                 {'choices': [{'finish_reason': 'stop', 'message': []}]},
                 {'choices': [{'finish_reason': 'stop', 'message': {'content': 'not JSON'}}]},
                 {'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]}]
        for response in cases:
            with self.subTest(response=response):
                with self.assertRaises(ExtractionError) as caught:
                    self.extractor_for(response)(OCR_TEXT)
                self.assertEqual(caught.exception.code, 'invalid_response')

    def test_incomplete_refusal_and_tool_output_are_not_invoice_drafts(self):
        cases = [(dict(groq_response()['choices'][0], finish_reason='length'), 'incomplete'),
                 ({'finish_reason': 'stop', 'message': {'refusal': 'SECRET upstream text'}}, 'refused'),
                 ({'finish_reason': 'stop', 'message': {'tool_calls': [{'function': 'x'}]}}, 'refused')]
        for choice, expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaises(ExtractionError) as caught:
                    self.extractor_for({'choices': [choice]})(OCR_TEXT)
                self.assertEqual(caught.exception.code, expected)
                self.assertNotIn('SECRET', caught.exception.message)

    def test_upstream_errors_do_not_leak_text_keys_or_retry(self):
        cases = [(401, 'authentication'), (403, 'authentication'),
                 (429, 'rate_limit'), (404, 'provider_rejected'), (500, 'provider_error')]
        for status, expected in cases:
            calls = []

            def opener(req, timeout):
                calls.append(req)
                raise error.HTTPError(GROQ_URL, status, 'SECRET upstream reason', {},
                                      io.BytesIO(b'SECRET invoice and fake-test-key'))

            with self.subTest(status=status):
                with self.assertRaises(ExtractionError) as caught:
                    GroqTextExtractor('fake-test-key', opener=opener)(OCR_TEXT)
                self.assertEqual(caught.exception.code, expected)
                self.assertNotIn('SECRET', caught.exception.message)
                self.assertNotIn('fake-test-key', caught.exception.message)
                self.assertEqual(len(calls), 1)

    def test_timeout_connection_and_oversize_response_have_safe_errors(self):
        for failure, expected in ((socket.timeout('SECRET'), 'timeout'),
                                  (error.URLError(socket.timeout('SECRET')), 'timeout'),
                                  (error.URLError('SECRET offline'), 'connection')):
            def opener(req, timeout):
                raise failure
            with self.subTest(expected=expected, failure_type=type(failure).__name__):
                with self.assertRaises(ExtractionError) as caught:
                    GroqTextExtractor('fake-test-key', opener=opener)(OCR_TEXT)
                self.assertEqual(caught.exception.code, expected)
                self.assertNotIn('SECRET', caught.exception.message)
        with self.assertRaises(ExtractionError) as caught:
            GroqTextExtractor('fake-test-key', opener=lambda *a, **k:
                              io.BytesIO(b'x' * (MAX_RESPONSE_BYTES + 1)))(OCR_TEXT)
        self.assertEqual(caught.exception.code, 'invalid_response')

    def test_invalid_keys_are_rejected_before_network(self):
        for key in ('', None, 'bad\nkey', 'bad\rkey', 'مفتاح'):
            with self.subTest(key_type=type(key).__name__):
                with self.assertRaises(ValueError):
                    GroqTextExtractor(key)


class FreeReaderServerTests(unittest.TestCase):
    @contextmanager
    def server(self, provider='ocr', **kwargs):
        with tempfile.TemporaryDirectory() as temp:
            app = Path(temp) / 'Rasam.html'
            app.write_text('<!doctype html><h1>Test</h1>', encoding='utf-8')
            self.ocr_calls = []

            def ocr_reader(upload):
                self.ocr_calls.append(upload)
                return {'text': OCR_TEXT, 'engine': 'test-local-engine',
                        'warnings': ['Fixture source warning.'], 'page_count': 1}

            settings = {'provider': provider, 'ocr_reader': ocr_reader, 'ocr_status': OCR_STATUS}
            settings.update(kwargs)
            server = create_server(app, **settings)
            thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
            thread.start()
            host = '127.0.0.1:{}'.format(server.server_port)

            def call(method, path, body=None):
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                headers = {'Host': host}
                if method == 'POST':
                    headers.update({'Origin': 'http://' + host, 'Content-Type': 'application/json',
                                    'X-Rasam-Token': status_body['csrf_token']})
                conn.request(method, path, body=json.dumps(body).encode() if body is not None else None,
                             headers=headers)
                response = conn.getresponse()
                payload = json.loads(response.read())
                code = response.status
                conn.close()
                return code, payload

            _, status_body = call('GET', '/api/status')
            try:
                yield call, status_body
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_local_ocr_reads_without_a_key_and_returns_source_text(self):
        with self.server() as (call, status):
            self.assertTrue(status['configured'])
            self.assertEqual(status['provider'], 'ocr')
            self.assertEqual(status['data_destination'], 'local')
            self.assertTrue(status['ocr']['available'])
            code, result = call('POST', '/api/extract', upload_fixture())
            self.assertEqual(code, 200, result)
            self.assertEqual(result['reading']['provider'], 'ocr')
            self.assertEqual(result['reading']['engine'], 'test-local-engine')
            self.assertEqual(result['reading']['source_text'], OCR_TEXT)
            self.assertEqual(Decimal(result['invoice']['total']), Decimal('115.00'))
            self.assertIn('Fixture source warning.', result['invoice']['warnings'])
            self.assertEqual(self.ocr_calls, [upload_fixture()])

    def test_groq_receives_only_text_after_local_ocr(self):
        ai_calls = []

        def boost(text):
            ai_calls.append(text)
            return invoice_fixture()

        with self.server('groq', api_key='fake-groq-key', extractor=boost) as (call, status):
            self.assertTrue(status['configured'])
            self.assertEqual(status['provider'], 'groq')
            self.assertEqual(status['data_destination'], 'groq')
            self.assertNotIn('fake-groq-key', json.dumps(status))
            code, result = call('POST', '/api/extract', upload_fixture())
            self.assertEqual(code, 200, result)
            self.assertEqual(ai_calls, [OCR_TEXT])
            self.assertEqual(result['reading']['provider'], 'groq')
            self.assertEqual(result['reading']['source_text'], OCR_TEXT)
            self.assertIn('Fixture source warning.', result['invoice']['warnings'])

    def test_groq_failure_returns_explicit_local_draft(self):
        def rate_limited(text):
            raise ExtractionError('rate_limit', 'Groq request limit reached.', 429)

        with self.server('groq', api_key='fake-groq-key', extractor=rate_limited) as (call, _):
            code, result = call('POST', '/api/extract', upload_fixture())
            self.assertEqual(code, 200, result)
            self.assertEqual(result['reading']['provider'], 'ocr')
            self.assertEqual(result['reading']['source_text'], OCR_TEXT)
            self.assertEqual(Decimal(result['invoice']['total']), Decimal('115.00'))
            warnings = ' '.join(result['invoice']['warnings']).lower()
            self.assertIn('groq', warnings)
            self.assertIn('local', warnings)
            self.assertIn('limit', warnings)

    def test_ocr_failure_never_sends_images_to_groq(self):
        ai_calls = []

        def broken_ocr(upload):
            raise ExtractionError('ocr_failed', 'The document could not be read locally.', 422)

        with self.server('groq', api_key='fake-groq-key', ocr_reader=broken_ocr,
                         extractor=lambda text: ai_calls.append(text)) as (call, _):
            code, result = call('POST', '/api/extract', upload_fixture())
            self.assertEqual(code, 422)
            self.assertEqual(result['code'], 'ocr_failed')
            self.assertEqual(ai_calls, [])

    def test_unavailable_ocr_reports_setup_need_and_never_reads(self):
        unavailable = dict(OCR_STATUS, available=False, message='Install local OCR dependencies.')
        with self.server(ocr_status=unavailable) as (call, status):
            self.assertFalse(status['configured'])
            self.assertFalse(status['ocr']['available'])
            code, result = call('POST', '/api/extract', upload_fixture())
            self.assertEqual(code, 503)
            self.assertEqual(result['code'], 'not_configured')
            self.assertEqual(self.ocr_calls, [])

    def test_groq_missing_key_is_not_configured(self):
        with self.server('groq', extractor=lambda text: invoice_fixture()) as (call, status):
            self.assertFalse(status['configured'])
            code, _ = call('POST', '/api/extract', upload_fixture())
            self.assertEqual(code, 503)
            self.assertEqual(self.ocr_calls, [])

    def test_bad_upload_is_rejected_before_local_reader(self):
        with self.server() as (call, _):
            code, result = call('POST', '/api/extract', dict(upload_fixture(), data_base64='invalid'))
            self.assertEqual(code, 400)
            self.assertEqual(self.ocr_calls, [])


if __name__ == '__main__':
    unittest.main()
