"""Offline local-model contracts; these do not measure Qwen invoice accuracy."""
import io
import json
import os
from pathlib import Path
import socket
import sys
import unittest
from unittest import mock
from urllib import error, request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rasam_ollama
from rasam_ai import ExtractionError, INVOICE_SCHEMA, MAX_RESPONSE_BYTES
from rasam_ollama import (CONTEXT_TOKENS, DEFAULT_OLLAMA_MODEL,
                          MAX_OLLAMA_TEXT_BYTES, OLLAMA_URL, OUTPUT_TOKENS,
                          OllamaTextExtractor, ollama_status, request_body)


TEXT = '''Tax Invoice
Supplier: Al Noor Stationery
Invoice Number: R-00042
Date: 2026-09-21
Currency: SAR
Net Amount: 100.00
VAT Amount: 15.00
Grand Total: 115.00
'''


def fixture():
    return {'supplier': 'Al Noor Stationery', 'invoiceNumber': 'R-00042',
            'date': '2026-09-21', 'currency': 'SAR', 'net': '100.00',
            'vat': '15.00', 'total': '115.00', 'is_invoice': True,
            'warnings': [], 'field_warnings': [], 'line_items': []}


def metadata():
    return {'details': {'format': 'gguf', 'family': 'qwen3'},
            'model_info': {'general.architecture': 'qwen3',
                           'general.parameter_count': 4000000000,
                           'qwen3.context_length': 262144},
            'capabilities': ['completion']}


def reply(invoice=None):
    return {'model': DEFAULT_OLLAMA_MODEL, 'done': True, 'done_reason': 'stop',
            'prompt_eval_count': 1900, 'eval_count': 180,
            'message': {'role': 'assistant', 'content': json.dumps(invoice or fixture())}}


class LocalAIContractTests(unittest.TestCase):
    def reader(self, response=None, model_info=None):
        self.calls = []

        def opener(req, timeout):
            self.calls.append((req, timeout))
            payload = (model_info if model_info is not None else metadata()) if req.full_url.endswith('/api/show') else response
            return io.BytesIO(json.dumps(payload).encode('utf-8'))

        return OllamaTextExtractor(opener=opener)

    def test_sends_only_text_to_verified_loopback_model_without_credentials(self):
        self.assertEqual(self.reader(reply())(TEXT), fixture())
        self.assertEqual([req.full_url for req, _ in self.calls],
                         [OLLAMA_URL + '/api/show', OLLAMA_URL + '/api/chat'])
        probe, generation = self.calls
        self.assertEqual(json.loads(probe[0].data), {'model': DEFAULT_OLLAMA_MODEL})
        self.assertNotIn('Al Noor', probe[0].data.decode())
        self.assertEqual(probe[1], 3)
        self.assertEqual(generation[1], 180)
        for req, _ in self.calls:
            self.assertEqual(req.get_method(), 'POST')
            self.assertIsNone(req.get_header('Authorization'))
        body = json.loads(generation[0].data)
        self.assertEqual(body['format'], INVOICE_SCHEMA)
        self.assertIn(TEXT, body['messages'][1]['content'])
        self.assertIn('untrusted', body['messages'][0]['content'])
        self.assertNotIn('tools', body)
        self.assertNotIn('images', body)
        self.assertIs(body['stream'], False)
        self.assertIs(body['think'], False)
        self.assertIs(body['truncate'], False)
        self.assertIs(body['shift'], False)
        self.assertEqual(body['keep_alive'], 0)
        self.assertEqual(body['options']['num_ctx'], 8192)
        self.assertEqual(body['options']['num_predict'], OUTPUT_TOKENS)
        self.assertEqual(json.loads(body['messages'][0]['content'].rsplit('\n', 1)[1]),
                         INVOICE_SCHEMA)
        self.assertIn('line_items', body['format']['required'])

    def test_proxy_environment_cannot_change_the_request_destination(self):
        with mock.patch.dict(os.environ, {'HTTP_PROXY': 'http://example.invalid:8888',
                                          'ALL_PROXY': 'http://example.invalid:8888',
                                          'OLLAMA_HOST': 'https://example.invalid',
                                          'OLLAMA_API_KEY': 'SHOULD_NOT_BE_USED'}):
            opener = rasam_ollama._local_opener()
            handlers = opener.__self__.handlers
            self.assertTrue(all(not handler.proxies for handler in handlers
                                if isinstance(handler, request.ProxyHandler)))
            self.reader(reply())(TEXT)
        for req, _ in self.calls:
            self.assertTrue(req.full_url.startswith('http://127.0.0.1:11434/'))
            self.assertIsNone(req.get_header('Authorization'))
            self.assertNotIn('SHOULD_NOT_BE_USED', req.data.decode())

    def test_redirect_handler_does_not_forward_request(self):
        handler = rasam_ollama._NoRedirect()
        req = request.Request(OLLAMA_URL + '/api/chat', data=b'private invoice')
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                self.assertIsNone(handler.redirect_request(req, None, status, 'redirect', {},
                                                           'https://example.invalid/collect'))

    def test_rejects_cloud_tags_hostnames_and_invalid_names_before_network(self):
        names = [None, '', 'qwen3', 'qwen3:cloud', 'qwen3:4b-cloud',
                 'gpt-oss:120b-CLOUD', 'https://ollama.com/qwen3:4b',
                 'example.com/qwen3:4b', 'account/qwen3:4b', 'qwen3:4b\n',
                 'qwen3:4b?remote=true', 'qwen3:4b:cloud', 'x' * 151]
        for name in names:
            with self.subTest(name=name):
                with self.assertRaises(ExtractionError) as caught:
                    OllamaTextExtractor(model=name, opener=lambda *a, **k: self.fail('Network called'))
                self.assertEqual(caught.exception.code, 'local_model_required')

    def test_rejects_cloud_backed_local_alias_before_invoice_request(self):
        for field in ('remote_host', 'remote_model'):
            with self.subTest(field=field):
                info = metadata()
                info[field] = 'https://remote.invalid/SECRET'
                reader = self.reader(reply(), info)
                with self.assertRaises(ExtractionError) as caught:
                    reader(TEXT)
                self.assertEqual(caught.exception.code, 'local_model_required')
                self.assertNotIn('SECRET', caught.exception.message)
                self.assertEqual(len(self.calls), 1)
                self.assertNotIn('Al Noor', self.calls[0][0].data.decode())

    def test_rejects_unverified_embedding_or_small_context_models(self):
        cases = [{}, {'details': 'not a dict'}, metadata(), metadata(), metadata(), metadata(), metadata()]
        cases[2]['capabilities'] = ['embedding']
        cases[3]['model_info']['qwen3.context_length'] = 4096
        cases[4]['model_info']['general.parameter_count'] = 0
        cases[5]['details']['format'] = 'remote'
        cases[6]['model_info']['general.architecture'] = 'unsupported-tokenizer'
        for info in cases:
            with self.subTest(info=info):
                with self.assertRaises(ExtractionError) as caught:
                    self.reader(reply(), info)(TEXT)
                self.assertEqual(caught.exception.code, 'ollama_model_unsupported')
                self.assertEqual(len(self.calls), 1)

    def test_utf8_budget_rejects_complete_oversized_input_without_truncating(self):
        reader = OllamaTextExtractor(opener=lambda *a, **k: self.fail('Network called'))
        for text, code in [('', 'empty_ocr'), (None, 'empty_ocr'), (' \n ', 'empty_ocr'),
                           ('x' * (MAX_OLLAMA_TEXT_BYTES + 1), 'text_too_long'),
                           ('ع' * (MAX_OLLAMA_TEXT_BYTES // 2 + 1), 'text_too_long'),
                           ('bad\ud800text', 'invalid_ocr')]:
            with self.subTest(code=code):
                with self.assertRaises(ExtractionError) as caught:
                    reader(text)
                self.assertEqual(caught.exception.code, code)
        allowed = 'x' * MAX_OLLAMA_TEXT_BYTES
        body = request_body(allowed)
        self.assertEqual(body['messages'][1]['content'], rasam_ollama._USER_PREFIX + allowed)
        prompt = body['messages']
        self.assertLessEqual(sum(len(message['content'].encode('utf-8')) for message in prompt)
                             + OUTPUT_TOKENS + rasam_ollama.TEMPLATE_MARGIN,
                             body['options']['num_ctx'])
        self.assertEqual(MAX_OLLAMA_TEXT_BYTES, 7424)

    def test_context_allocation_tracks_full_utf8_text_at_each_boundary(self):
        overhead = (len((rasam_ollama._SYSTEM + rasam_ollama._USER_PREFIX).encode('utf-8'))
                    + OUTPUT_TOKENS + rasam_ollama.TEMPLATE_MARGIN)
        boundaries = [(8192 - overhead, 8192), (8192 - overhead + 1, 12288),
                      (12288 - overhead, 12288), (12288 - overhead + 1, CONTEXT_TOKENS),
                      (MAX_OLLAMA_TEXT_BYTES, CONTEXT_TOKENS)]
        for size, context in boundaries:
            self.assertGreater(size, 0)
            for alphabet in ('english', 'arabic'):
                with self.subTest(size=size, alphabet=alphabet):
                    text = 'x' * size if alphabet == 'english' else 'ع' * (size // 2) + 'x' * (size % 2)
                    self.assertEqual(len(text.encode('utf-8')), size)
                    body = request_body(text)
                    self.assertEqual(body['messages'][1]['content'], rasam_ollama._USER_PREFIX + text)
                    self.assertEqual(body['options']['num_ctx'], context)
                    self.assertLessEqual(overhead + size, context)
                    self.assertFalse(body['truncate'])
                    self.assertFalse(body['shift'])

    def test_unprinted_amounts_are_cleared_and_arabic_numbers_match(self):
        result = self.reader(reply())('Tax invoice Net ١٠٠٫٠٠ VAT rate 15%')
        self.assertEqual(result['net'], '100.00')
        self.assertIsNone(result['vat'])
        self.assertIsNone(result['total'])
        self.assertEqual({w['field'] for w in result['field_warnings']}, {'vat', 'total'})

    def test_invalid_individual_fields_do_not_discard_valid_siblings(self):
        for field, value in (('total', 'NaN'), ('currency', 'KWD')):
            with self.subTest(field=field):
                invoice = fixture()
                invoice[field] = value
                result = self.reader(reply(invoice))(TEXT)
                self.assertIsNone(result[field])
                for other in ('supplier', 'invoiceNumber', 'date', 'net', 'vat'):
                    self.assertEqual(result[other], fixture()[other])
                self.assertIn(field, {warning['field'] for warning in result['field_warnings']})

    def test_unknown_keys_and_invalid_root_are_not_salvaged(self):
        invoice = fixture()
        invoice['unexpected'] = True
        for invalid in (invoice, [fixture()], 'invoice', 42, None):
            with self.subTest(invalid=invalid):
                response = reply()
                response['message']['content'] = json.dumps(invalid)
                with self.assertRaises(ExtractionError) as caught:
                    self.reader(response)(TEXT)
                self.assertEqual(caught.exception.code, 'invalid_response')

    def test_json_decimal_normalization_does_not_round_printed_amount(self):
        response = reply()
        response['message']['content'] = json.dumps(fixture()).replace(
            '"100.00"', '100.1234567890123456789')
        result = self.reader(response)(TEXT.replace('100.00', '100.1234567890123456789'))
        self.assertEqual(result['net'], '100.1234567890123456789')

    def test_incomplete_or_overflowed_generation_is_rejected(self):
        changes = [{'done': False}, {'done_reason': 'length'},
                   {'prompt_eval_count': CONTEXT_TOKENS},
                   {'prompt_eval_count': None}, {'prompt_eval_count': True},
                   {'eval_count': -1}]
        for change in changes:
            with self.subTest(change=change):
                response = reply()
                response.update(change)
                with self.assertRaises(ExtractionError) as caught:
                    self.reader(response)(TEXT)
                self.assertEqual(caught.exception.code, 'incomplete')

    def test_generation_counts_are_checked_against_requested_context(self):
        overhead = (len((rasam_ollama._SYSTEM + rasam_ollama._USER_PREFIX).encode('utf-8'))
                    + OUTPUT_TOKENS + rasam_ollama.TEMPLATE_MARGIN)
        for target_length in (len(TEXT.encode('utf-8')), 8192 - overhead + 1,
                              12288 - overhead + 1):
            text = TEXT + ' ' * (target_length - len(TEXT.encode('utf-8')))
            context = request_body(text)['options']['num_ctx']
            with self.subTest(context=context):
                response = reply()
                response['prompt_eval_count'] = context - response['eval_count'] - 1
                self.assertEqual(self.reader(response)(text), fixture())
                response['prompt_eval_count'] += 1
                with self.assertRaises(ExtractionError) as caught:
                    self.reader(response)(text)
                self.assertEqual(caught.exception.code, 'incomplete')

    def test_bad_message_tool_calls_or_mismatched_models_are_rejected(self):
        changes = [{'message': None}, {'message': {'role': 'user', 'content': '{}'}},
                   {'message': {'role': 'assistant', 'content': 'SECRET invalid JSON'}},
                   {'message': {'role': 'assistant', 'content': '1e999999999999999999999999999'}},
                   {'message': {'role': 'assistant', 'content': '{}', 'tool_calls': ['x']}},
                   {'model': 'different:local'}]
        for change in changes:
            with self.subTest(change=change):
                response = reply()
                response.update(change)
                with self.assertRaises(ExtractionError) as caught:
                    self.reader(response)(TEXT)
                self.assertEqual(caught.exception.code, 'invalid_response')
                self.assertNotIn('SECRET', caught.exception.message)

    def test_remote_result_is_rejected_even_after_local_metadata_check(self):
        response = reply()
        response['remote_model'] = 'unexpected remote'
        with self.assertRaises(ExtractionError) as caught:
            self.reader(response)(TEXT)
        self.assertEqual(caught.exception.code, 'local_model_required')

    def test_missing_model_server_errors_timeout_and_offline_fail_safely(self):
        failures = [(error.HTTPError(OLLAMA_URL, 404, 'SECRET', {}, None), 'ollama_model_missing'),
                    (error.HTTPError(OLLAMA_URL, 403, 'SECRET', {}, None), 'local_model_required'),
                    (error.HTTPError(OLLAMA_URL, 422, 'SECRET', {}, None), 'ollama_rejected'),
                    (error.HTTPError(OLLAMA_URL, 500, 'SECRET', {}, None), 'ollama_error'),
                    (error.HTTPError(OLLAMA_URL, 307, 'SECRET', {}, None), 'ollama_error'),
                    (socket.timeout('SECRET'), 'timeout'),
                    (error.URLError(socket.timeout('SECRET')), 'timeout'),
                    (error.URLError('SECRET'), 'ollama_unavailable')]
        for failure, code in failures:
            calls = []

            def opener(req, timeout):
                calls.append(req)
                raise failure

            with self.subTest(code=code):
                with self.assertRaises(ExtractionError) as caught:
                    OllamaTextExtractor(opener=opener)(TEXT)
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn('SECRET', caught.exception.message)
                self.assertEqual(len(calls), 1)

    def test_oversized_malformed_and_error_envelopes_are_rejected(self):
        for raw, code in [(b'x' * (MAX_RESPONSE_BYTES + 1), 'invalid_response'),
                          (b'[]', 'invalid_response'), (b'not json SECRET', 'invalid_response'),
                          (b'{"error":"SECRET"}', 'ollama_error')]:
            with self.subTest(code=code, length=len(raw)):
                with self.assertRaises(ExtractionError) as caught:
                    OllamaTextExtractor(opener=lambda *a, **k: io.BytesIO(raw))(TEXT)
                self.assertEqual(caught.exception.code, code)
                self.assertNotIn('SECRET', caught.exception.message)

    def test_status_reports_ready_without_loading_model_or_sending_invoice(self):
        calls = []

        def opener(req, timeout):
            calls.append(req)
            return io.BytesIO(json.dumps(metadata()).encode())

        with mock.patch.object(rasam_ollama, '_local_opener', return_value=opener):
            status = ollama_status()
        self.assertIs(status['available'], True)
        self.assertEqual(status['model'], DEFAULT_OLLAMA_MODEL)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].full_url, OLLAMA_URL + '/api/show')
        self.assertEqual(json.loads(calls[0].data), {'model': DEFAULT_OLLAMA_MODEL})

    def test_status_handles_stopped_server_without_raising(self):
        with mock.patch.object(rasam_ollama, '_check_local_model',
                               side_effect=ExtractionError('ollama_unavailable', 'Open Ollama.')):
            status = ollama_status()
        self.assertEqual(status, {'available': False, 'model': DEFAULT_OLLAMA_MODEL,
                                  'message': 'Open Ollama.'})


if __name__ == '__main__':
    unittest.main()
