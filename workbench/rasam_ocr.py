"""Local, optional OCR engines for invoice drafts.

Importing this module never installs packages or downloads a model. PaddleOCR
loads lazily on the first image that needs OCR. Its first use may download the
public model weights; invoice images are passed as local temporary paths only.
PDFium and Pillow are optional. Tesseract is a separate local command-line app.
"""
import base64
from contextlib import closing
from functools import lru_cache
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import unicodedata
import warnings as python_warnings

from rasam_ai import ExtractionError, validate_upload

MAX_PAGES = 10
MAX_TEXT_CHARS = 60_000
MAX_IMAGE_PIXELS = 20_000_000
MAX_RENDER_PIXELS = 12_000_000
MAX_RENDER_SIDE = 6000
MAX_PAGE_POINTS = 14_400
OCR_TIMEOUT = 60
DOCUMENT_TIMEOUT = 120
_PADDLE = None
_PADDLE_LOCK = threading.Lock()
# PDFium is not thread safe, including across different documents.
_PDF_LOCK = threading.Lock()


def _has_module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, AttributeError):
        return False


def _too_large(message):
    raise ExtractionError('document_too_large', message, 413)


def _bounded_text(text):
    if len(text) > MAX_TEXT_CHARS:
        _too_large('This document contains too much text. Split it into smaller files.')
    return text


@lru_cache(maxsize=1)
def _tesseract_info():
    executable = shutil.which('tesseract')
    if not executable:
        return None, []
    try:
        output = subprocess.run([executable, '--list-langs'], capture_output=True,
                                timeout=5, check=True, encoding='utf-8', errors='replace')
        installed = set(output.stdout.splitlines())
        languages = [language for language in ('eng', 'ara') if language in installed]
        return executable, languages
    except (OSError, subprocess.SubprocessError):
        return None, []


def _image_engine():
    preferred = os.environ.get('RASAM_OCR_ENGINE', 'auto').strip().lower()
    if preferred not in ('auto', 'paddle', 'tesseract'):
        return None
    if not _has_module('PIL'):
        return None
    if preferred in ('auto', 'paddle') and _has_module('paddleocr') and _has_module('paddle'):
        return 'paddleocr'
    executable, languages = _tesseract_info()
    if preferred in ('auto', 'tesseract') and executable and languages:
        return 'tesseract'
    return None


def local_ocr_status():
    """Report installed capability without importing heavy models or networking."""
    engine = _image_engine()
    if engine == 'paddleocr':
        return {'available': True, 'engine': engine, 'languages': ['ar', 'en'],
                'message': 'PaddleOCR is installed. First use loads Arabic and English model weights; verify every draft.'}
    if engine == 'tesseract':
        languages = _tesseract_info()[1]
        message = 'Local Tesseract is ready. Verify every draft.'
        if 'ara' not in languages:
            message += ' Arabic recognition is unavailable: install the Arabic language pack.'
        return {'available': True, 'engine': engine,
                'languages': [('ar' if item == 'ara' else 'en') for item in languages],
                'message': message}
    if _has_module('pypdfium2'):
        return {'available': True, 'engine': 'pdf-text', 'languages': [],
                'message': 'Text-only PDFs can be read locally. Install PaddleOCR or Tesseract to read photos and scanned PDFs.'}
    return {'available': False, 'engine': 'unavailable', 'languages': [],
            'message': 'Install the local OCR dependencies using the workbench setup guide.'}


def _load_paddle():
    global _PADDLE
    if _PADDLE is None:
        from paddleocr import PaddleOCR
        _PADDLE = PaddleOCR(
            text_detection_model_name='PP-OCRv5_mobile_det',
            text_recognition_model_name='arabic_PP-OCRv5_mobile_rec',
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            device='cpu',
        )
    return _PADDLE


def _paddle_lines(result):
    """Keep detected rows and column spacing; never reverse Arabic characters."""
    payload = result.json if hasattr(result, 'json') else result
    if not isinstance(payload, dict):
        raise ValueError('Unsupported PaddleOCR output')
    payload = payload.get('res', payload)
    texts = payload.get('rec_texts', [])
    boxes = payload.get('rec_boxes', [])
    scores = payload.get('rec_scores', [])
    if len(texts) > MAX_TEXT_CHARS:
        _too_large('This document contains too much text. Split it into smaller files.')
    records, total_chars, low_quality = [], 0, False
    for index, value in enumerate(texts):
        if not isinstance(value, str):
            raise ValueError('Unsupported PaddleOCR text')
        total_chars += len(value) + 1
        if total_chars > MAX_TEXT_CHARS:
            _too_large('This document contains too much text. Split it into smaller files.')
        text = value.strip()
        if not text:
            continue
        if index < len(scores) and float(scores[index]) < 0.8:
            low_quality = True
        if index < len(boxes) and len(boxes[index]) == 4:
            left, top, right, bottom = map(float, boxes[index])
            if not all(math.isfinite(v) for v in (left, top, right, bottom)):
                raise ValueError('Invalid text positions')
            records.append((top, left, max(1.0, bottom - top), text))
        else:
            # Current v3 emits rec_boxes. Preserve engine order if unavailable.
            return _bounded_text('\n'.join(str(item) for item in texts)), low_quality
    rows = []
    for top, left, height, text in sorted(records):
        if rows and abs(rows[-1]['top'] - top) <= min(rows[-1]['height'], height) * 0.45:
            rows[-1]['parts'].append((left, text))
        else:
            rows.append({'top': top, 'height': height, 'parts': [(left, text)]})
    return _bounded_text('\n'.join('\t'.join(text for _, text in sorted(row['parts']))
                                   for row in rows)), low_quality


def _paddle_text(image_path):
    # Serial inference also avoids racing initialization and model downloads.
    with _PADDLE_LOCK:
        model = _load_paddle()
        chunks, low_quality = [], False
        for result in model.predict(str(image_path)):
            text, uncertain = _paddle_lines(result)
            chunks.append(text)
            low_quality = low_quality or uncertain
            _bounded_text('\n'.join(chunks))
    messages = ['Arabic and mixed-language invoice accuracy still needs review against your own invoices.']
    if low_quality:
        messages.append('Some text was difficult to recognize. Compare the draft with the original invoice.')
    return '\n'.join(chunks), messages


def _tesseract_text(image_path, temp_dir):
    executable, languages = _tesseract_info()
    if not executable or not languages:
        raise ExtractionError('ocr_unavailable', 'Install Tesseract and its English and Arabic language packs.', 503)
    output_base = Path(temp_dir) / 'tesseract-result'
    try:
        subprocess.run([executable, str(image_path), str(output_base),
                        '-l', '+'.join(languages), '--psm', '3',
                        '-c', 'preserve_interword_spaces=1'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=OCR_TIMEOUT, check=True)
        output_path = output_base.with_suffix('.txt')
        if output_path.stat().st_size > MAX_TEXT_CHARS * 4:
            _too_large('This document contains too much text. Split it into smaller files.')
        text = _bounded_text(output_path.read_text(encoding='utf-8', errors='replace'))
    except subprocess.TimeoutExpired:
        raise ExtractionError('ocr_timeout', 'Local reading took too long. Try a smaller or clearer invoice.', 504) from None
    except (OSError, subprocess.SubprocessError):
        raise ExtractionError('ocr_failed', 'Local OCR could not read this page. Try a clearer image.', 422) from None
    finally:
        output_base.with_suffix('.txt').unlink(missing_ok=True)
    messages = []
    if 'ara' not in languages:
        messages.append('Arabic recognition is unavailable because the Tesseract Arabic language pack is missing. Arabic fields may be unreadable or incorrect.')
    if 'eng' not in languages:
        messages.append('The English language pack is missing. Verify all English text and identifiers.')
    return text, messages


def _read_image(image_path, temp_dir):
    engine = _image_engine()
    if engine is None:
        raise ExtractionError('ocr_unavailable',
                              'Install Pillow plus PaddleOCR or Tesseract to read invoice images and scans.', 503)
    if engine == 'paddleocr':
        try:
            text, messages = _paddle_text(image_path)
            return text, engine, messages
        except ExtractionError:
            raise
        except Exception:
            # An installed package may lack usable model weights. A fallback is
            # permitted only in auto mode, and is disclosed in the result.
            if os.environ.get('RASAM_OCR_ENGINE', 'auto').lower() == 'auto' and _tesseract_info()[1]:
                text, messages = _tesseract_text(image_path, temp_dir)
                messages.insert(0, 'PaddleOCR could not start. This draft used local Tesseract instead.')
                return text, 'tesseract', messages
            raise ExtractionError('ocr_failed',
                                  'PaddleOCR could not load or read this image. Check the model installation in the setup guide.', 503) from None
    text, messages = _tesseract_text(image_path, temp_dir)
    return text, engine, messages


def _normalize_image(data, path):
    if not _has_module('PIL'):
        raise ExtractionError('ocr_unavailable', 'Install Pillow to read invoice images.', 503)
    from PIL import Image, ImageOps
    try:
        with python_warnings.catch_warnings():
            python_warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
                if width * height > MAX_IMAGE_PIXELS:
                    _too_large('Choose an image smaller than 20 megapixels.')
                if getattr(image, 'n_frames', 1) != 1:
                    raise ExtractionError('unsupported_file', 'Use a single-frame invoice image or a PDF.', 415)
                normalized = ImageOps.exif_transpose(image).convert('RGB')
                try:
                    normalized.save(path, format='PNG')
                finally:
                    normalized.close()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        _too_large('Choose an image smaller than 20 megapixels.')
    except ExtractionError:
        raise
    except Exception:
        raise ExtractionError('ocr_failed', 'This image is damaged or unsupported. Upload another copy.', 422) from None


def _usable_pdf_text(text):
    significant = [char for char in text if not char.isspace()]
    if len(significant) < 30 or sum(char.isalnum() for char in significant) < 20:
        return False
    bad = sum(char == '\ufffd' or unicodedata.category(char) in ('Co', 'Cs', 'Cc')
              for char in significant)
    return bad == 0


def _page_has_images(page, pdfium):
    # OCR every page containing a raster, even when it also has a text header.
    # This avoids dropping a scanned invoice body below an embedded-text header.
    return next(page.get_objects(filter=[pdfium.raw.FPDF_PAGEOBJ_IMAGE]), None) is not None


def _read_pdf(data, temp_dir):
    if not _has_module('pypdfium2'):
        raise ExtractionError('ocr_unavailable', 'Install pypdfium2 to read PDF invoices locally.', 503)
    import pypdfium2 as pdfium
    chunks, engines, messages = [], [], []
    with _PDF_LOCK:
        try:
            with closing(pdfium.PdfDocument(data)) as document:
                page_count = len(document)
                if page_count > MAX_PAGES:
                    _too_large('Read up to 10 PDF pages at a time. Split this document into smaller files.')
                if page_count == 0:
                    raise ExtractionError('ocr_failed', 'This PDF has no pages.', 422)
                for index in range(page_count):
                    with closing(document[index]) as page:
                        width, height = page.get_size()
                        if (not all(math.isfinite(value) and 0 < value <= MAX_PAGE_POINTS
                                    for value in (width, height))):
                            _too_large('This PDF has an unsupported page size. Export it using a standard paper size.')
                        with closing(page.get_textpage()) as text_page:
                            if text_page.count_chars() > MAX_TEXT_CHARS:
                                _too_large('This document contains too much text. Split it into smaller files.')
                            native_text = _bounded_text(text_page.get_text_bounded(errors='replace'))
                        if _usable_pdf_text(native_text) and not _page_has_images(page, pdfium):
                            text, engine = native_text, 'pdf-text'
                        else:
                            if not _has_module('PIL'):
                                raise ExtractionError('ocr_unavailable', 'Install Pillow to read scanned PDF pages.', 503)
                            scale = min(2.5, math.sqrt(MAX_RENDER_PIXELS / (width * height)),
                                        MAX_RENDER_SIDE / width, MAX_RENDER_SIDE / height)
                            # Allow for renderer ceil rounding at the resource boundary.
                            scale *= 0.999
                            image_path = Path(temp_dir) / 'page.png'
                            with closing(page.render(scale=scale)) as bitmap:
                                with closing(bitmap.to_pil()) as rendered:
                                    if rendered.width * rendered.height > MAX_RENDER_PIXELS:
                                        _too_large('This PDF page is too large to render safely.')
                                    rendered.save(image_path, format='PNG')
                            text, engine, page_messages = _read_image(image_path, temp_dir)
                            messages.extend(page_messages)
                        if not text.strip():
                            messages.append(f'No readable text was found on page {index + 1}. Check the original page.')
                        chunks.append(f'--- Page {index + 1} ---\n{text.strip()}')
                        engines.append(engine)
                        _bounded_text('\n\n'.join(chunks))
        except ExtractionError:
            raise
        except Exception:
            raise ExtractionError('ocr_failed', 'This PDF could not be read. Try an unlocked, undamaged PDF or a clear image.', 422) from None
    return {'text': '\n\n'.join(chunks), 'engine': '+'.join(dict.fromkeys(engines)),
            'warnings': list(dict.fromkeys(messages)), 'page_count': page_count}


def _read_document_local(upload, temp_dir):
    """Worker implementation, also callable directly by engine tests."""
    upload = validate_upload(upload)
    data = base64.b64decode(upload['data_base64'], validate=True)
    if upload['mime_type'] == 'application/pdf':
        return _read_pdf(data, temp_dir)
    image_path = Path(temp_dir) / 'invoice.png'
    _normalize_image(data, image_path)
    text, engine, messages = _read_image(image_path, temp_dir)
    if not text.strip():
        messages.append('No readable text was found. Try a sharper, upright invoice image.')
    return {'text': _bounded_text(text.strip()), 'engine': engine,
            'warnings': list(dict.fromkeys(messages)), 'page_count': 1}


def _terminate_worker(process):
    # Kill the complete process group on POSIX so a running Tesseract child
    # cannot outlive an expired document. Windows taskkill supplies the same
    # tree behavior; a final kill covers an already-exiting process.
    if os.name == 'posix':
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        taskkill = shutil.which('taskkill')
        if taskkill:
            try:
                subprocess.run([taskkill, '/PID', str(process.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=5, check=False)
            except (OSError, subprocess.SubprocessError):
                pass
        process.kill()
    process.wait()


def _run_worker(directory):
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), '--ocr-worker', str(directory)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=(os.name == 'posix'),
    )
    try:
        process.wait(timeout=DOCUMENT_TIMEOUT)
    except subprocess.TimeoutExpired:
        _terminate_worker(process)
        raise ExtractionError('ocr_timeout',
                              'Local reading exceeded two minutes. Try fewer pages. On first PaddleOCR use, check that the model weights finished downloading.', 504) from None
    if process.returncode != 0:
        raise ExtractionError('ocr_failed', 'Local OCR could not finish. Check the installation or try another invoice.', 422)


def read_document(upload):
    """Read locally with a hard document deadline and private temporary files.

    One isolated process per document keeps PDFium and Paddle state independent
    and makes slow native calls cancellable. Paddle loads once per document and
    reuses that pipeline for all pages; downloaded weights remain in its cache.
    """
    upload = validate_upload(upload)
    with tempfile.TemporaryDirectory(prefix='rasam-ocr-') as temp_dir:
        directory = Path(temp_dir)
        (directory / 'input.json').write_text(json.dumps(upload), encoding='utf-8')
        try:
            _run_worker(directory)
            result_path = directory / 'result.json'
            if not result_path.is_file():
                raise ExtractionError('ocr_failed', 'Local OCR could not finish. Check the installation or try another invoice.', 422)
            if result_path.stat().st_size > MAX_TEXT_CHARS * 6 + 40_000:
                _too_large('This document contains too much text. Split it into smaller files.')
            payload = json.loads(result_path.read_text(encoding='utf-8'))
            if 'error' in payload:
                raise ExtractionError(payload['code'], payload['error'], payload['status'])
            _bounded_text(payload['text'])
            return payload
        except ExtractionError:
            raise
        except Exception:
            raise ExtractionError('ocr_failed', 'Local OCR could not finish. Check the installation or try another invoice.', 422) from None


def _worker_main(directory):
    try:
        upload = json.loads((directory / 'input.json').read_text(encoding='utf-8'))
        result = _read_document_local(upload, str(directory))
    except ExtractionError as error:
        result = {'error': error.message, 'code': error.code, 'status': error.status}
    except Exception:
        result = {'error': 'Local OCR could not read this document. Try another copy.',
                  'code': 'ocr_failed', 'status': 422}
    (directory / 'result.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--ocr-worker':
        _worker_main(Path(sys.argv[2]))
    elif sys.argv[1:] == ['--download-models']:
        # Explicit setup command can finish a slow first download before the
        # two-minute invoice reading deadline applies. It reads no invoices.
        try:
            with _PADDLE_LOCK:
                _load_paddle()
            print('PaddleOCR Arabic and English model weights are ready for local reading.')
        except Exception:
            raise SystemExit('PaddleOCR setup failed. Check the installation and internet connection, then try again.') from None
    else:
        raise SystemExit('Run start_rasam.py to use local invoice reading.')
