"""Offline integration tests. No credentials, model calls, or external network."""
import base64
import copy
import http.client
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib import error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rasam_ai import (API_URL, DEFAULT_MODEL, FIELD_NAMES, MAX_JSON_BYTES,
                      ExtractionError, OpenAIExtractor, build_request_body,
                      parse_response, validate_invoice, validate_upload)
from start_rasam import create_server


def invoice_fixture():
    return {
        'supplier': 'شركة النور', 'invoiceNumber': '000482', 'date': '2026-09-21',
        'currency': 'SAR', 'net': '100.00', 'vat': '15.00', 'total': '115.00',
        'is_invoice': True, 'warnings': [], 'field_warnings': [],
        'line_items': [{'description': 'Paper / ورق', 'quantity': '2',
                        'unit_price': '50.00', 'net_amount': '100.00'}],
    }


def upload_fixture(mime='application/pdf', data=b'%PDF-1.7\nFictional test fixture'):
    return {'filename': 'invoice.pdf', 'mime_type': mime,
            'data_base64': base64.b64encode(data).decode('ascii')}


def response_fixture(invoice=None):
    return {'status': 'completed', 'output': [{'type': 'message', 'content': [
        {'type': 'output_text', 'text': json.dumps(invoice or invoice_fixture(), ensure_ascii=False)}]}]}


class AIContractTests(unittest.TestCase):
    def test_real_wire_format_pdf_and_image_without_network(self):
        captured = []

        def fake_open(req, timeout):
            captured.append((req, timeout))
            return io.BytesIO(json.dumps(response_fixture()).encode())

        reader = OpenAIExtractor('fake-test-key', model='test-vision-model', opener=fake_open)
        result = reader(upload_fixture())
        self.assertEqual(result['invoiceNumber'], '000482')
        self.assertEqual(result['supplier'], 'شركة النور')
        req, timeout = captured[0]
        self.assertEqual(req.full_url, API_URL)
        self.assertEqual(req.get_method(), 'POST')
        self.assertEqual(req.get_header('Authorization'), 'Bearer fake-test-key')
        self.assertEqual(timeout, 90)
        body = json.loads(req.data)
        self.assertEqual(body['model'], 'test-vision-model')
        self.assertIs(body['store'], False)
        self.assertTrue(body['text']['format']['strict'])
        self.assertEqual(body['text']['format']['schema']['additionalProperties'], False)
        file_part = body['input'][0]['content'][1]
        self.assertEqual(file_part['type'], 'input_file')
        self.assertTrue(file_part['file_data'].startswith('data:application/pdf;base64,'))
        self.assertNotIn('fake-test-key', req.data.decode())
        image = build_request_body(upload_fixture('image/png', b'\x89PNG\r\n\x1a\nFAKE'), DEFAULT_MODEL)
        part = image['input'][0]['content'][1]
        self.assertEqual(part['type'], 'input_image')
        self.assertEqual(part['detail'], 'high')
        self.assertTrue(part['image_url'].startswith('data:image/png;base64,'))

    def test_actual_signatures_and_base64_are_checked(self):
        for mime, content in (
                ('application/pdf', b'%PDF-1.7 test'),
                ('image/jpeg', b'\xff\xd8\xff\xe0test'),
                ('image/png', b'\x89PNG\r\n\x1a\ntest'),
                ('image/webp', b'RIFF\x10\x00\x00\x00WEBPtest')):
            with self.subTest(mime=mime):
                self.assertEqual(validate_upload(upload_fixture(mime, content))['mime_type'], mime)
        for bad in (
                dict(upload_fixture(), data_base64='not base64!'),
                dict(upload_fixture(), data_base64='data:application/pdf;base64,AAAA'),
                dict(upload_fixture(), mime_type='image/png'),
                dict(upload_fixture(), mime_type='text/html'),
                dict(upload_fixture(), filename='../private.txt'),
                dict(upload_fixture(), data_base64=''),
                dict(upload_fixture(), filename='bad\nname.pdf'),
                dict(upload_fixture(), data_base64='أبجد')):
            with self.subTest(bad=bad):
                with self.assertRaises(ExtractionError):
                    validate_upload(bad)
        with patch('rasam_ai.MAX_FILE_BYTES', 3):
            with self.assertRaises(ExtractionError) as caught:
                validate_upload(upload_fixture())
            self.assertEqual(caught.exception.code, 'file_too_large')

    def test_missing_fields_remain_null_and_negatives_are_not_corrected(self):
        example = invoice_fixture()
        example.update(net='-100.00', vat=None, total='-115.00')
        example['field_warnings'] = [{'field': 'vat', 'message': 'No explicit tax amount.'}]
        example['warnings'] = ['Credit note: review separately.']
        self.assertEqual(validate_invoice(example), example)
        self.assertIsNone(example['vat'])
        self.assertEqual(example['total'], '-115.00')

    def test_totals_are_not_silently_repaired(self):
        example = invoice_fixture()
        example['total'] = '999.00'
        self.assertEqual(validate_invoice(example)['total'], '999.00')

    def test_invalid_model_values_rejected(self):
        for field, bad_value in (
                ('net', 'NaN'), ('net', 'Infinity'), ('net', '1e3'), ('net', 100),
                ('net', '1,000.00'), ('date', '2026-02-30'), ('date', '21/09/2026'),
                ('currency', 'KWD'), ('supplier', ''), ('is_invoice', 1),
                ('line_items', [{'description': 'x', 'quantity': 'NaN', 'unit_price': None, 'net_amount': None}]),
                ('field_warnings', [{'field': 'unknown', 'message': 'x'}])):
            with self.subTest(field=field, value=bad_value):
                fixture = invoice_fixture()
                fixture[field] = bad_value
                with self.assertRaises(ExtractionError) as caught:
                    validate_invoice(fixture)
                self.assertEqual(caught.exception.code, 'invalid_response')

    def test_non_invoice_and_multiple_invoice_result_stays_empty(self):
        example = {name: None for name in FIELD_NAMES}
        example.update(is_invoice=False, warnings=['Multiple invoices. Split the file.'],
                       field_warnings=[], line_items=[])
        self.assertFalse(validate_invoice(example)['is_invoice'])
        example['total'] = '12.00'
        with self.assertRaises(ExtractionError):
            validate_invoice(example)

    def test_model_refusal_and_incomplete_have_distinct_errors(self):
        cases = [({'status': 'incomplete', 'output': []}, 'incomplete'),
                 ({'status': 'completed', 'output': [{'type': 'message', 'content': [
                     {'type': 'refusal', 'refusal': 'raw secret upstream refusal'}]}]}, 'refused'),
                 ({'output': []}, 'invalid_response'),
                 ({'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{'}]}]}, 'invalid_response')]
        for response, expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaises(ExtractionError) as caught:
                    parse_response(response)
                self.assertEqual(caught.exception.code, expected)
                self.assertNotIn('raw secret', caught.exception.message)

    def test_upstream_failures_are_safe_distinct_and_never_retried(self):
        for status, provider_code, expected in (
                (401, 'bad_api_key', 'authentication'), (403, None, 'authentication'),
                (429, 'insufficient_quota', 'quota'), (429, 'rate_limit_exceeded', 'rate_limit'),
                (500, None, 'provider_error'), (404, None, 'provider_rejected')):
            calls = []

            def fail(req, timeout):
                calls.append(req)
                raw = json.dumps({'error': {'code': provider_code, 'message': 'SECRET source text and key'}}).encode()
                raise error.HTTPError(API_URL, status, 'upstream', {}, io.BytesIO(raw))

            with self.subTest(status=status, code=provider_code):
                with self.assertRaises(ExtractionError) as caught:
                    OpenAIExtractor('fake-test-key', opener=fail)(upload_fixture())
                self.assertEqual(caught.exception.code, expected)
                self.assertNotIn('SECRET', caught.exception.message)
                self.assertNotIn('fake-test-key', caught.exception.message)
                self.assertEqual(len(calls), 1)
        for failure, expected in ((socket.timeout(), 'timeout'),
                                  (error.URLError(socket.timeout()), 'timeout'),
                                  (error.URLError('offline'), 'connection')):
            def fail(req, timeout):
                raise failure
            with self.assertRaises(ExtractionError) as caught:
                OpenAIExtractor('fake-test-key', opener=fail)(upload_fixture())
            self.assertEqual(caught.exception.code, expected)


class LocalServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Path(self.temp.name) / 'Rasam.html'
        self.app.write_text('<!doctype html><h1>Rasam test</h1>', encoding='utf-8')
        (Path(self.temp.name) / 'secret.txt').write_text('DO NOT SERVE', encoding='utf-8')
        self.calls = []
        self.handler = lambda upload: invoice_fixture()

        def extract(upload):
            self.calls.append(upload)
            return self.handler(upload)

        self.server = create_server(self.app, api_key='fake-test-key', extractor=extract)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()
        self.host = '127.0.0.1:{}'.format(self.server.server_port)
        status, _, body = self.call('GET', '/api/status')
        self.assertEqual(status, 200)
        self.token = body['csrf_token']

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def call(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        if isinstance(body, dict):
            body = json.dumps(body).encode()
        merged = {'Host': self.host}
        if method == 'POST':
            merged.update({'Origin': 'http://' + self.host, 'Content-Type': 'application/json',
                           'X-Rasam-Token': self.token})
        if headers:
            merged.update(headers)
        merged = {key: value for key, value in merged.items() if value is not None}
        connection.request(method, path, body=body, headers=merged)
        response = connection.getresponse()
        data = response.read()
        response_headers = dict(response.getheaders())
        status = response.status
        connection.close()
        if data and 'application/json' in response_headers.get('Content-Type', ''):
            data = json.loads(data)
        return status, response_headers, data

    def test_status_and_valid_roundtrip(self):
        status, headers, body = self.call('GET', '/api/status')
        self.assertTrue(body['configured'])
        self.assertEqual(body['model'], DEFAULT_MODEL)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertNotIn('fake-test-key', json.dumps(body))
        self.assertNotIn('Access-Control-Allow-Origin', headers)
        status, _, body = self.call('POST', '/api/extract', upload_fixture())
        self.assertEqual(status, 200)
        self.assertEqual(body['invoice'], invoice_fixture())
        self.assertEqual(len(self.calls), 1)

    def test_only_app_file_is_served(self):
        for path in ('/', '/Rasam.html'):
            self.assertEqual(self.call('GET', path)[0], 200)
        for path in ('/secret.txt', '/start_rasam.py', '/rasam_ai.py', '/../secret.txt', '/api/key'):
            status, _, data = self.call('GET', path)
            self.assertEqual(status, 404)
            self.assertNotIn('DO NOT SERVE', json.dumps(data))
        status, _, body = self.call('HEAD', '/')
        self.assertEqual(status, 200)
        self.assertEqual(body, b'')

    def test_rebinding_and_foreign_origin_requests_never_reach_extractor(self):
        cases = [{'Host': 'attacker.example:{}'.format(self.server.server_port)},
                 {'Host': 'localhost:1'}, {'Origin': 'https://attacker.example'},
                 {'Origin': 'null'}, {'Origin': None},
                 {'Origin': 'http://127.0.0.1:1'}, {'Sec-Fetch-Site': 'cross-site'},
                 {'Sec-Fetch-Site': 'same-site'}]
        for headers in cases:
            with self.subTest(headers=headers):
                status, _, body = self.call('POST', '/api/extract', upload_fixture(), headers)
                self.assertEqual(status, 403)
                self.assertEqual(body['code'], 'forbidden')
        self.assertEqual(self.call('GET', '/api/status', headers={'Host': 'attacker.example'})[0], 403)
        self.assertEqual(self.call('OPTIONS', '/api/extract')[0], 403)
        self.assertEqual(self.calls, [])

    def test_missing_and_invalid_csrf_tokens(self):
        for token in (None, '', 'wrong-token'):
            status, _, body = self.call('POST', '/api/extract', upload_fixture(), {'X-Rasam-Token': token})
            self.assertEqual(status, 403)
            self.assertEqual(body['code'], 'invalid_token')
        self.assertEqual(self.calls, [])

    def test_malformed_and_oversize_uploads_never_reach_extractor(self):
        cases = [(b'{bad json', {}, 400),
                 (dict(upload_fixture(), data_base64='!!!!'), {}, 400),
                 (dict(upload_fixture(), mime_type='image/png'), {}, 415),
                 (upload_fixture(), {'Content-Type': 'text/plain'}, 415),
                 (b'', {'Content-Length': str(MAX_JSON_BYTES + 1)}, 413)]
        for payload, headers, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(self.call('POST', '/api/extract', payload, headers)[0], expected)
        self.assertEqual(self.calls, [])

    def test_safe_provider_errors_and_unexpected_failure(self):
        def failure(upload):
            raise ExtractionError('authentication', 'Key was rejected.', 502)
        self.handler = failure
        status, _, body = self.call('POST', '/api/extract', upload_fixture())
        self.assertEqual(status, 502)
        self.assertEqual(body['code'], 'authentication')
        def unexpected(upload):
            raise RuntimeError('SECRET test key and invoice contents')
        self.handler = unexpected
        status, _, body = self.call('POST', '/api/extract', upload_fixture())
        self.assertEqual(status, 500)
        self.assertEqual(body['code'], 'server_error')
        self.assertNotIn('SECRET', json.dumps(body))

    def test_unconfigured_server_remains_manual(self):
        other = create_server(self.app, api_key=None, extractor=lambda upload: self.fail('must not extract'))
        thread = threading.Thread(target=lambda: other.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()
        original, original_host = self.server, self.host
        try:
            self.server = other
            self.host = '127.0.0.1:{}'.format(other.server_port)
            status, _, body = self.call('GET', '/api/status')
            self.assertFalse(body['configured'])
            status, _, body = self.call('POST', '/api/extract', upload_fixture(), {'X-Rasam-Token': body['csrf_token']})
            self.assertEqual(status, 503)
            self.assertEqual(body['code'], 'not_configured')
        finally:
            self.server, self.host = original, original_host
            other.shutdown()
            other.server_close()
            thread.join(timeout=2)

    def test_two_requests_allowed_third_busy_then_capacity_recovers(self):
        barrier = threading.Barrier(3)
        release = threading.Event()
        results = []
        def blocking(upload):
            barrier.wait(timeout=3)
            release.wait(timeout=3)
            return invoice_fixture()
        self.handler = blocking
        def worker():
            results.append(self.call('POST', '/api/extract', upload_fixture())[0])
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        try:
            barrier.wait(timeout=3)
            status, _, body = self.call('POST', '/api/extract', upload_fixture())
            self.assertEqual(status, 429)
            self.assertEqual(body['code'], 'busy')
        finally:
            release.set()
            for thread in threads:
                thread.join(timeout=3)
        self.assertEqual(results, [200, 200])
        self.handler = lambda upload: invoice_fixture()
        self.assertEqual(self.call('POST', '/api/extract', upload_fixture())[0], 200)


if __name__ == '__main__':
    unittest.main(verbosity=2)
