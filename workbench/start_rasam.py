"""Open Rasam locally with free OCR and optional server-side AI assistance."""
from argparse import ArgumentParser
import getpass
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
from urllib.parse import urlsplit
import webbrowser

from rasam_ai import (DEFAULT_MODEL, MAX_JSON_BYTES, ExtractionError,
                      OpenAIExtractor, validate_invoice, validate_upload)
from rasam_groq import DEFAULT_GROQ_MODEL, GroqTextExtractor
from rasam_ocr import local_ocr_status, read_document
from rasam_text import draft_from_text


def create_server(app_path, port=0, api_key=None, model=None, extractor=None,
                  provider='openai', ocr_reader=None, ocr_status=None):
    """Create a loopback server without starting its event loop.

    Engines/status are injectable for offline tests. The CLI defaults to local
    OCR; the OpenAI function default preserves the original integration API.
    """
    app = Path(app_path).resolve()
    if provider not in ('ocr', 'groq', 'openai'):
        raise ValueError('Unknown invoice reader provider')
    key = (api_key or '').strip()
    if key and (not key.isascii() or '\r' in key or '\n' in key):
        raise ValueError('Invalid API key configuration')
    defaults = {'ocr': 'local-ocr', 'groq': DEFAULT_GROQ_MODEL, 'openai': DEFAULT_MODEL}
    chosen_model = (model or defaults[provider]).strip() or defaults[provider]
    local_status = ocr_status if ocr_status is not None else local_ocr_status()
    configured = bool(key) if provider == 'openai' else bool(local_status['available'] and (provider == 'ocr' or key))
    engine = extractor
    if configured and engine is None and provider != 'ocr':
        engine = (GroqTextExtractor if provider == 'groq' else OpenAIExtractor)(key, chosen_model)
    local_reader = ocr_reader or read_document
    labels = {'ocr': 'Local OCR', 'groq': 'Local OCR + Groq', 'openai': 'OpenAI'}
    message = local_status['message']
    if provider == 'groq':
        message += (' Groq key configured; recognized text is sent to Groq when you read.' if key else
                    ' Restart with --provider groq and enter a Groq API key, or choose local OCR.')
    elif provider == 'openai':
        message = ('Key configured; each read sends the selected document to OpenAI.' if configured else
                   'OpenAI reading needs an API key. Restart with --provider openai and enter your key there.')
    csrf_token = secrets.token_urlsafe(32)
    capacity = threading.BoundedSemaphore(2 if provider == 'openai' else 1)

    def read_invoice(upload):
        if provider == 'openai':
            return validate_invoice(engine(upload)), {'provider': 'openai', 'engine': chosen_model, 'source_text': ''}
        result = local_reader(upload)
        source_text = result['text']
        warnings = list(result.get('warnings', []))
        metadata = {'provider': 'ocr', 'engine': result['engine'], 'source_text': source_text}
        if provider == 'groq':
            try:
                invoice = validate_invoice(engine(source_text))
                invoice['warnings'] = (warnings + invoice['warnings'])[:30]
                metadata.update(provider='groq', engine=result['engine'] + ' + ' + chosen_model)
                return validate_invoice(invoice), metadata
            except ExtractionError as exc:
                warnings.insert(0, exc.message + ' Showing a local OCR draft; AI assistance was not applied.')
        return draft_from_text(source_text, warnings=warnings), metadata

    class Handler(BaseHTTPRequestHandler):
        # Never echo filenames, keys, invoice text or errors into terminal logs.
        server_version = 'Rasam'
        sys_version = ''

        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def log_message(self, *args):
            pass

        def _send(self, status, body, content_type='application/json; charset=utf-8', head=False):
            if isinstance(body, dict):
                body = json.dumps(body, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.close_connection = True
            if not head:
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError, socket.timeout):
                    pass

        def _error(self, code, message, status=400):
            self._send(status, {'error': message, 'code': code})

        def _valid_local_request(self, require_origin=False):
            hosts = self.headers.get_all('Host', [])
            allowed_hosts = ('localhost:{}'.format(self.server.server_port),
                             '127.0.0.1:{}'.format(self.server.server_port))
            if len(hosts) != 1 or hosts[0] not in allowed_hosts:
                self._error('forbidden', 'Open Rasam using the localhost address shown in its launcher.', 403)
                return False
            origins = self.headers.get_all('Origin', [])
            if (len(origins) > 1 or (require_origin and not origins)
                    or (origins and origins[0] != 'http://' + hosts[0])):
                self._error('forbidden', 'Open Rasam in its own localhost browser tab and try again.', 403)
                return False
            if self.headers.get('Sec-Fetch-Site') in ('cross-site', 'same-site'):
                self._error('forbidden', 'Open Rasam in its own localhost browser tab and try again.', 403)
                return False
            return True

        def _get(self, head=False):
            if not self._valid_local_request():
                return
            path = urlsplit(self.path).path
            if path == '/api/status':
                self._send(200, {'configured': configured, 'model': chosen_model,
                                 'csrf_token': csrf_token, 'provider': provider,
                                 'label': labels[provider], 'message': message, 'ocr': local_status,
                                 'data_destination': 'local' if provider == 'ocr' else provider}, head=head)
            elif path in ('/', '/Rasam.html'):
                try:
                    content = app.read_bytes()
                except OSError:
                    self._error('missing_app', 'Keep Rasam.html beside the Rasam launcher.', 404)
                    return
                self._send(200, content, 'text/html; charset=utf-8', head=head)
            else:
                self._error('not_found', 'This Rasam page was not found.', 404)

        def do_GET(self):
            self._get()

        def do_HEAD(self):
            self._get(head=True)

        def do_POST(self):
            if not self._valid_local_request(require_origin=True):
                return
            if urlsplit(self.path).path != '/api/extract':
                self._error('not_found', 'This Rasam endpoint was not found.', 404)
                return
            tokens = self.headers.get_all('X-Rasam-Token', [])
            if (len(tokens) != 1 or not tokens[0].isascii()
                    or not hmac.compare_digest(tokens[0], csrf_token)):
                self._error('invalid_token', 'Your Rasam connection expired. Refresh the page and try again.', 403)
                return
            if self.headers.get('Transfer-Encoding'):
                self._error('invalid_upload', 'The upload format is not supported.')
                return
            if self.headers.get_content_type() != 'application/json':
                self._error('invalid_upload', 'Upload the invoice through Rasam.', 415)
                return
            lengths = self.headers.get_all('Content-Length', [])
            if len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdigit():
                self._error('invalid_upload', 'The upload size is missing or invalid.', 411)
                return
            length = int(lengths[0])
            if length > MAX_JSON_BYTES:
                self._error('file_too_large', 'Choose an invoice smaller than 20 MB.', 413)
                return
            if not configured:
                self._error('not_configured', message, 503)
                return
            if not capacity.acquire(blocking=False):
                self._error('busy', 'The reader is busy. Wait for the current reading to finish.', 429)
                return
            try:
                raw = self.rfile.read(length)
                if len(raw) != length:
                    self._error('invalid_upload', 'The upload was interrupted. Please upload the invoice again.')
                    return
                try:
                    payload = json.loads(raw)
                except (ValueError, UnicodeDecodeError, RecursionError):
                    self._error('invalid_upload', 'The upload is damaged. Please upload the invoice again.')
                    return
                upload = validate_upload(payload)
                invoice, reading = read_invoice(upload)
                self._send(200, {'invoice': invoice, 'reading': reading})
            except ExtractionError as exc:
                self._error(exc.code, exc.message, exc.status)
            except (TimeoutError, socket.timeout):
                self._error('timeout', 'The upload took too long. Please try again.', 408)
            except Exception:
                self._error('server_error', 'Rasam could not finish reading this invoice. Try again or enter the details manually.', 500)
            finally:
                capacity.release()

        def do_OPTIONS(self):
            self._error('forbidden', 'Open Rasam in its own localhost browser tab.', 403)

    class LocalServer(ThreadingHTTPServer):
        daemon_threads = True

        def handle_error(self, request, client_address):
            # Never print a traceback that could include uploaded content or secrets.
            pass

    return LocalServer(('127.0.0.1', port), Handler)


def main():
    parser = ArgumentParser(description='Open Rasam with free local OCR and optional AI assistance.')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--no-key-prompt', action='store_true',
                        help='Read the selected provider key from the environment without prompting.')
    parser.add_argument('--provider', choices=('ocr', 'groq', 'openai'),
                        default=os.environ.get('RASAM_PROVIDER', 'ocr'),
                        help='ocr is free and local; groq adds optional cloud AI; openai is a paid alternative.')
    args = parser.parse_args()
    app = Path(__file__).resolve().parent / 'Rasam.html'
    if not app.is_file():
        parser.error('Keep all Rasam files together. Extract the whole ZIP before running its launcher.')
    if not 0 <= args.port <= 65535:
        parser.error('Port must be between 0 and 65535.')
    provider = args.provider
    if provider not in ('ocr', 'groq', 'openai'):
        parser.error('RASAM_PROVIDER must be ocr, groq or openai.')
    key_name = 'GROQ_API_KEY' if provider == 'groq' else 'OPENAI_API_KEY'
    api_key = os.environ.get(key_name, '').strip() if provider != 'ocr' else ''
    model = (os.environ.get('GROQ_MODEL', DEFAULT_GROQ_MODEL) if provider == 'groq' else
             os.environ.get('OPENAI_MODEL', DEFAULT_MODEL) if provider == 'openai' else 'local-ocr')
    if provider != 'ocr' and not api_key and not args.no_key_prompt and sys.stdin.isatty():
        label = 'Groq' if provider == 'groq' else 'OpenAI'
        print('Enter your {} API key here. It is hidden and kept only in memory.'.format(label))
        print('Groq receives recognized text and has free-tier limits.' if provider == 'groq' else
              'OpenAI receives the selected document. API usage charges apply.')
        print('Press Enter to use free local OCR instead.')
        try:
            api_key = getpass.getpass(label + ' API key: ').strip()
        except (EOFError, KeyboardInterrupt):
            print('\nStarting with local OCR.')
            api_key = ''
        if not api_key:
            provider, model = 'ocr', 'local-ocr'
    if '\r' in api_key or '\n' in api_key or (api_key and not api_key.isascii()):
        parser.error('The API key contains invalid characters. Enter only the key text.')
    try:
        server = create_server(app, args.port, api_key=api_key, model=model, provider=provider)
    except OSError:
        try:
            server = create_server(app, 0, api_key=api_key, model=model, provider=provider)
        except OSError:
            parser.error('Rasam could not open a local port. Close another launcher and try again.')
    url = 'http://localhost:{}/'.format(server.server_port)
    print('Rasam is running at ' + url, flush=True)
    if provider == 'ocr':
        print('Local OCR: invoice content stays on this computer. ' + local_ocr_status()['message'], flush=True)
    else:
        print('{}: {}.'.format(provider, 'key configured' if api_key else 'key missing'), flush=True)
        print('Each read sends recognized text to Groq.' if provider == 'groq' else
              'Each read sends the selected document to OpenAI; API charges apply.', flush=True)
    print('Keep this window open. Press Ctrl+C to stop.', flush=True)
    if not args.no_browser:
        timer = threading.Timer(0.3, lambda: webbrowser.open(url))
        timer.daemon = True
        timer.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nRasam stopped.')
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
