"""Offline HTTP checks for local AI routing and cloud-free startup."""
import base64
from contextlib import contextmanager, redirect_stdout
from decimal import Decimal
import http.client
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rasam_ai import ExtractionError
from rasam_ollama import DEFAULT_OLLAMA_MODEL, OllamaTextExtractor
import start_rasam


OCR_TEXT = '''Tax Invoice
Supplier: Al Noor Stationery
Invoice Number: R-00042
Date: 2026-09-21
Currency: SAR
Net Amount: 100.00
VAT Amount: 15.00
Grand Total: 115.00
'''
OCR_STATUS = {'available': True, 'engine': 'fixture-ocr', 'languages': ['eng'],
              'message': 'Local OCR is available.'}
OLLAMA_STATUS = {'available': True, 'model': DEFAULT_OLLAMA_MODEL,
                 'message': 'The selected local model is available.'}
CLOUD_ENV = {'OPENAI_API_KEY': 'unused-openai-secret', 'GROQ_API_KEY': 'unused-groq-secret'}


def invoice_fixture():
    return {'supplier': 'Al Noor Stationery', 'invoiceNumber': 'R-00042',
            'date': '2026-09-21', 'currency': 'SAR', 'net': '100.00',
            'vat': '15.00', 'total': '115.00', 'is_invoice': True,
            'warnings': [], 'field_warnings': [], 'line_items': []}


def upload_fixture():
    return {'filename': 'invoice.pdf', 'mime_type': 'application/pdf',
            'data_base64': base64.b64encode(b'%PDF-1.7\nTest document').decode('ascii')}


class LocalAIServerTests(unittest.TestCase):
    @contextmanager
    def server(self, **overrides):
        self.ocr_calls = []
        self.ai_calls = []

        def read(upload):
            self.ocr_calls.append(upload)
            return {'text': OCR_TEXT, 'engine': 'fixture-ocr', 'page_count': 1,
                    'warnings': ['Review the original source.']}

        def extract(text):
            self.ai_calls.append(text)
            return invoice_fixture()

        with tempfile.TemporaryDirectory() as temp:
            app = Path(temp) / 'Rasam.html'
            app.write_text('<!doctype html><h1>Local AI test</h1>', encoding='utf-8')
            settings = {'provider': 'ollama', 'ocr_reader': read, 'ocr_status': OCR_STATUS,
                        'ollama_info': OLLAMA_STATUS, 'extractor': extract}
            settings.update(overrides)
            with (patch.dict(os.environ, CLOUD_ENV),
                  patch.object(start_rasam, 'GroqTextExtractor') as groq,
                  patch.object(start_rasam, 'OpenAIExtractor') as openai):
                server = start_rasam.create_server(app, **settings)
                thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01),
                                          daemon=True)
                thread.start()
                host = '127.0.0.1:{}'.format(server.server_port)
                token = None

                def call(method, path, body=None):
                    conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                    headers = {'Host': host}
                    if method == 'POST':
                        headers.update({'Origin': 'http://' + host,
                                        'Content-Type': 'application/json', 'X-Rasam-Token': token})
                    conn.request(method, path, body=json.dumps(body).encode() if body is not None else None,
                                 headers=headers)
                    response = conn.getresponse()
                    code, result = response.status, json.loads(response.read())
                    conn.close()
                    return code, result

                _, status = call('GET', '/api/status')
                token = status['csrf_token']
                try:
                    yield call, status
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)
                    groq.assert_not_called()
                    openai.assert_not_called()

    def test_local_pipeline_needs_no_key_and_preserves_source_and_provenance(self):
        with self.server() as (call, status):
            self.assertTrue(status['configured'])
            self.assertEqual(status['provider'], 'ollama')
            self.assertEqual(status['data_destination'], 'local')
            self.assertTrue(status['ollama']['available'])
            self.assertEqual(status['model'], DEFAULT_OLLAMA_MODEL)
            code, result = call('POST', '/api/extract', upload_fixture())
            self.assertEqual(code, 200, result)
            self.assertEqual(self.ocr_calls, [upload_fixture()])
            self.assertEqual(self.ai_calls, [OCR_TEXT])
            self.assertEqual(result['reading'], {'provider': 'ollama',
                             'engine': 'fixture-ocr + ' + DEFAULT_OLLAMA_MODEL, 'source_text': OCR_TEXT})
            self.assertEqual(result['invoice']['invoiceNumber'], 'R-00042')
            self.assertIn('Review the original source.', result['invoice']['warnings'])
            for secret in CLOUD_ENV.values():
                self.assertNotIn(secret, json.dumps(status) + json.dumps(result))

    def test_both_ocr_and_local_model_must_be_available_before_reading(self):
        cases = [({'ocr_status': dict(OCR_STATUS, available=False, message='Install OCR.')}, 'Install OCR.'),
                 ({'ollama_info': dict(OLLAMA_STATUS, available=False, message='Pull the local model.')},
                  'Pull the local model.')]
        for settings, expected_message in cases:
            with self.subTest(settings=settings), self.server(**settings) as (call, status):
                self.assertFalse(status['configured'])
                self.assertEqual(status['data_destination'], 'local')
                self.assertIn(expected_message, status['message'])
                code, result = call('POST', '/api/extract', upload_fixture())
                self.assertEqual(code, 503)
                self.assertEqual(result['code'], 'not_configured')
                self.assertIn(expected_message, result['error'])
                self.assertEqual(self.ocr_calls, [])
                self.assertEqual(self.ai_calls, [])

    def test_model_timeout_returns_labelled_ocr_draft_without_cloud_fallback(self):
        def timeout(text):
            self.ai_calls.append(text)
            raise ExtractionError('timeout', 'The local model took too long.', 504)

        with self.server(extractor=timeout) as (call, _):
            code, result = call('POST', '/api/extract', upload_fixture())
            self.assertEqual(code, 200, result)
            self.assertEqual(self.ai_calls, [OCR_TEXT])
            self.assertEqual(result['reading'], {'provider': 'ocr', 'engine': 'fixture-ocr',
                                                'source_text': OCR_TEXT})
            self.assertEqual(Decimal(result['invoice']['total']), Decimal('115.00'))
            warnings = ' '.join(result['invoice']['warnings'])
            self.assertIn('local model took too long', warnings)
            self.assertIn('AI assistance was not applied', warnings)

    def test_invalid_model_output_is_not_represented_as_successful_ai(self):
        with self.server(extractor=lambda text: {'total': '999999.00'}) as (call, _):
            code, result = call('POST', '/api/extract', upload_fixture())
            self.assertEqual(code, 200, result)
            self.assertEqual(result['reading']['provider'], 'ocr')
            self.assertEqual(Decimal(result['invoice']['total']), Decimal('115.00'))
            self.assertIn('AI assistance was not applied', ' '.join(result['invoice']['warnings']))

    def test_partial_local_model_draft_keeps_usable_fields_through_http(self):
        draft = invoice_fixture()
        draft.update(date='not a date', net=100, vat='15%', warnings=None)
        calls = []

        def local_reply(request, timeout):
            calls.append(request.full_url)
            if request.full_url.endswith('/api/show'):
                payload = {'details': {'format': 'gguf'},
                           'capabilities': ['completion'],
                           'model_info': {'general.architecture': 'qwen3',
                                          'general.parameter_count': 1700000000,
                                          'qwen3.context_length': 40960}}
            else:
                payload = {'model': DEFAULT_OLLAMA_MODEL, 'done': True,
                           'done_reason': 'stop', 'prompt_eval_count': 1900,
                           'eval_count': 180, 'message': {'role': 'assistant',
                                                        'content': json.dumps(draft)}}
            return io.BytesIO(json.dumps(payload).encode())

        with self.server(extractor=OllamaTextExtractor(opener=local_reply)) as (call, _):
            code, result = call('POST', '/api/extract', upload_fixture())
        self.assertEqual(code, 200, result)
        self.assertEqual(result['reading']['provider'], 'ollama')
        self.assertEqual(result['reading']['source_text'], OCR_TEXT)
        invoice = result['invoice']
        self.assertEqual(invoice['supplier'], 'Al Noor Stationery')
        self.assertEqual(invoice['invoiceNumber'], 'R-00042')
        self.assertEqual(Decimal(invoice['net']), Decimal('100'))
        self.assertEqual(invoice['total'], '115.00')
        self.assertIsNone(invoice['date'])
        self.assertIsNone(invoice['vat'])
        self.assertTrue({'date', 'vat'}.issubset({w['field'] for w in invoice['field_warnings']}))
        self.assertNotIn('AI assistance was not applied', ' '.join(invoice['warnings']))
        self.assertEqual(calls, ['http://127.0.0.1:11434/api/show',
                                 'http://127.0.0.1:11434/api/chat'])

    def test_failed_ocr_does_not_call_local_ai_or_cloud(self):
        def failed_ocr(upload):
            raise ExtractionError('ocr_failed', 'The source could not be read locally.', 422)

        with self.server(ocr_reader=failed_ocr) as (call, _):
            code, result = call('POST', '/api/extract', upload_fixture())
            self.assertEqual(code, 422)
            self.assertEqual(result['code'], 'ocr_failed')
            self.assertEqual(self.ai_calls, [])
            self.assertNotIn('invoice', result)


class LocalAIStartupTests(unittest.TestCase):
    def run_launcher(self, arguments, environment):
        server = Mock(server_port=8765)
        server.serve_forever.side_effect = KeyboardInterrupt
        output = io.StringIO()
        with (patch.dict(os.environ, environment, clear=True),
              patch.object(sys, 'argv', ['start_rasam.py', '--no-browser'] + arguments),
              patch.object(start_rasam, 'create_server', return_value=server) as create,
              patch.object(start_rasam, 'local_ocr_status', return_value=OCR_STATUS),
              patch.object(start_rasam.getpass, 'getpass') as prompt,
              patch.object(sys.stdin, 'isatty', return_value=True),
              patch.object(start_rasam.webbrowser, 'open') as browser,
              redirect_stdout(output)):
            start_rasam.main()
        prompt.assert_not_called()
        browser.assert_not_called()
        server.serve_forever.assert_called_once_with()
        server.server_close.assert_called_once_with()
        self.assertEqual(create.call_count, 1)
        for secret in CLOUD_ENV.values():
            self.assertNotIn(secret, output.getvalue())
        return create.call_args.kwargs, output.getvalue()

    def test_ollama_launcher_ignores_cloud_keys_and_never_prompts_for_one(self):
        settings, output = self.run_launcher(['--provider', 'ollama'], CLOUD_ENV)
        self.assertEqual(settings['provider'], 'ollama')
        self.assertEqual(settings['api_key'], '')
        self.assertEqual(settings['model'], DEFAULT_OLLAMA_MODEL)
        self.assertIn('invoice content stays on this computer', output)
        self.assertIn('No API key or API charges', output)

    def test_default_remains_free_ocr_even_when_cloud_keys_exist(self):
        settings, output = self.run_launcher([], CLOUD_ENV)
        self.assertEqual(settings['provider'], 'ocr')
        self.assertEqual(settings['api_key'], '')
        self.assertIn('Local OCR: invoice content stays on this computer', output)

    def test_explicit_ollama_model_setting_reaches_local_server(self):
        settings, _ = self.run_launcher([], dict(CLOUD_ENV, RASAM_PROVIDER='ollama',
                                                OLLAMA_MODEL='qwen3:8b'))
        self.assertEqual(settings['provider'], 'ollama')
        self.assertEqual(settings['model'], 'qwen3:8b')
        self.assertEqual(settings['api_key'], '')


if __name__ == '__main__':
    unittest.main()
