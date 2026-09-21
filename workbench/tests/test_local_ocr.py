"""Safety tests and optional real-engine smoke tests using fictional invoices."""
import base64
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rasam_ocr as ocr
from rasam_ai import ExtractionError


def upload(data, mime='image/png', filename='invoice.png'):
    return {'filename': filename, 'mime_type': mime,
            'data_base64': base64.b64encode(data).decode('ascii')}


def local_read(payload):
    with tempfile.TemporaryDirectory(prefix='rasam-ocr-test-') as directory:
        return ocr._read_document_local(payload, directory)


def image_bytes():
    from PIL import Image, ImageDraw, ImageFont
    picture = Image.new('RGB', (1200, 900), 'white')
    draw = ImageDraw.Draw(picture)
    try:
        font = ImageFont.truetype('DejaVuSans.ttf', 36)
    except OSError:
        font = ImageFont.load_default()
    for row, text in enumerate((
        'TAX INVOICE', 'Supplier: Gulf Supply LLC', 'Invoice Number: INV-0042',
        'Invoice Date: 2026-09-21', 'Currency: SAR', 'Net Amount: 100.00',
        'VAT Amount: 15.00', 'Grand Total: 115.00',
    )):
        draw.text((70, 65 + row * 90), text, font=font, fill='black')
    buffer = io.BytesIO()
    picture.save(buffer, format='PNG')
    picture.close()
    return buffer.getvalue()


def pdf_bytes(pages=1, image=False):
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    buffer = io.BytesIO()
    document = canvas.Canvas(buffer, pagesize=(612, 792))
    for index in range(pages):
        if image:
            # A readable text header must not hide a scanned invoice body.
            document.drawString(40, 760, 'Document export - supplier invoices for human review')
            document.drawImage(ImageReader(io.BytesIO(image_bytes())),
                               30, 140, width=550, height=412.5)
        else:
            for row, text in enumerate(('TAX INVOICE', 'Supplier: Gulf Supply LLC',
                                        f'Invoice Number: INV-00{index + 42}',
                                        'Invoice Date: 2026-09-21', 'Currency: SAR',
                                        'Net Amount: 100.00', 'VAT Amount: 15.00',
                                        'Grand Total: 115.00')):
                document.drawString(40, 730 - row * 40, text)
        document.showPage()
    document.save()
    return buffer.getvalue()


HAVE_PIL = importlib.util.find_spec('PIL') is not None
HAVE_PDF = (importlib.util.find_spec('pypdfium2') is not None
            and importlib.util.find_spec('reportlab') is not None)
HAVE_TESSERACT = bool(ocr._tesseract_info()[0] and 'eng' in ocr._tesseract_info()[1])


class LocalOCRSafetyTests(unittest.TestCase):
    def test_status_does_not_initialize_or_download_model(self):
        with patch.object(ocr, '_has_module', return_value=True), \
                patch.object(ocr, '_load_paddle') as load, \
                patch.dict(os.environ, {'RASAM_OCR_ENGINE': 'auto'}):
            status = ocr.local_ocr_status()
        self.assertEqual(status['engine'], 'paddleocr')
        self.assertEqual(status['languages'], ['ar', 'en'])
        load.assert_not_called()

    def test_missing_arabic_pack_is_disclosed(self):
        with patch.object(ocr, '_has_module', side_effect=lambda name: name == 'PIL'), \
                patch.object(ocr, '_tesseract_info', return_value=('/usr/bin/tesseract', ['eng'])), \
                patch.dict(os.environ, {'RASAM_OCR_ENGINE': 'auto'}):
            status = ocr.local_ocr_status()
        self.assertEqual(status['languages'], ['en'])
        self.assertIn('Arabic recognition is unavailable', status['message'])

    def test_no_dependencies_does_not_break_status(self):
        with patch.object(ocr, '_has_module', return_value=False):
            self.assertFalse(ocr.local_ocr_status()['available'])

    def test_pdf_only_status_is_explicit(self):
        with patch.object(ocr, '_has_module', side_effect=lambda name: name == 'pypdfium2'):
            status = ocr.local_ocr_status()
        self.assertEqual(status['engine'], 'pdf-text')
        self.assertIn('Text-only PDFs', status['message'])

    def test_rejects_excess_text_instead_of_truncating(self):
        with self.assertRaises(ExtractionError) as caught:
            ocr._bounded_text('x' * (ocr.MAX_TEXT_CHARS + 1))
        self.assertEqual(caught.exception.code, 'document_too_large')

    def test_pdf_text_quality_rejects_sparse_and_broken_text(self):
        self.assertFalse(ocr._usable_pdf_text('Page 1'))
        self.assertFalse(ocr._usable_pdf_text('Invoice ' * 20 + '\ufffd'))
        self.assertFalse(ocr._usable_pdf_text('\ue000' * 100))
        self.assertTrue(ocr._usable_pdf_text('فاتورة ضريبية المورد شركة الخليج المجموع ١١٥٫٠٠'))

    def test_paddle_positions_preserve_rows_and_arabic(self):
        result = {'res': {'rec_texts': ['115.00', 'فاتورة ضريبية', 'Total'],
                          'rec_boxes': [[300, 100, 400, 120], [20, 20, 300, 40], [20, 101, 130, 121]],
                          'rec_scores': [0.99, 0.99, 0.6]}}
        text, uncertain = ocr._paddle_lines(result)
        self.assertEqual(text, 'فاتورة ضريبية\nTotal\t115.00')
        self.assertTrue(uncertain)

    def test_tesseract_timeout_is_safe(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(ocr, '_tesseract_info', return_value=('/usr/bin/tesseract', ['eng'])), \
                patch.object(ocr.subprocess, 'run', side_effect=subprocess.TimeoutExpired('tesseract', 60)):
            with self.assertRaises(ExtractionError) as caught:
                ocr._tesseract_text(Path(directory) / 'invoice.png', directory)
        self.assertEqual(caught.exception.code, 'ocr_timeout')
        self.assertNotIn(directory, caught.exception.message)

    def test_document_timeout_terminates_worker(self):
        process = Mock()
        process.wait.side_effect = subprocess.TimeoutExpired('local-worker', 120)
        with patch.object(ocr.subprocess, 'Popen', return_value=process), \
                patch.object(ocr, '_terminate_worker') as terminate:
            with self.assertRaises(ExtractionError) as caught:
                ocr._run_worker(Path('/private/input'))
        terminate.assert_called_once_with(process)
        process.wait.assert_called_once_with(timeout=120)
        self.assertEqual(caught.exception.code, 'ocr_timeout')
        self.assertNotIn('/private', caught.exception.message)

    def test_tesseract_command_is_fixed_and_output_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            def fake_run(command, **kwargs):
                self.assertEqual(command[0], '/trusted/tesseract')
                self.assertEqual(command[4], 'eng+ara')
                self.assertEqual(kwargs['timeout'], 60)
                self.assertNotIn('shell', kwargs)
                Path(command[2] + '.txt').write_text('x' * (ocr.MAX_TEXT_CHARS + 1))
            with patch.object(ocr, '_tesseract_info', return_value=('/trusted/tesseract', ['eng', 'ara'])), \
                    patch.object(ocr.subprocess, 'run', side_effect=fake_run):
                with self.assertRaises(ExtractionError) as caught:
                    ocr._tesseract_text(Path(directory) / 'invoice.png', directory)
            self.assertEqual(caught.exception.code, 'document_too_large')
            self.assertFalse((Path(directory) / 'tesseract-result.txt').exists())

    def test_paddle_failure_falls_back_with_warning(self):
        with patch.object(ocr, '_image_engine', return_value='paddleocr'), \
                patch.object(ocr, '_paddle_text', side_effect=RuntimeError('private upstream details')), \
                patch.object(ocr, '_tesseract_info', return_value=('/trusted/tesseract', ['eng'])), \
                patch.object(ocr, '_tesseract_text', return_value=('Invoice', ['Arabic is unavailable'])), \
                patch.dict(os.environ, {'RASAM_OCR_ENGINE': 'auto'}):
            text, engine, messages = ocr._read_image('/tmp/fixed.png', '/tmp')
        self.assertEqual((text, engine), ('Invoice', 'tesseract'))
        self.assertIn('PaddleOCR could not start', messages[0])
        self.assertNotIn('private', ' '.join(messages))

    @unittest.skipUnless(HAVE_PIL, 'Pillow is optional')
    def test_private_temporary_files_are_cleaned_on_failure(self):
        observed_paths = []
        def fail_read(directory):
            observed_paths.extend([Path(directory) / 'input.json', Path(directory)])
            self.assertTrue(observed_paths[0].exists())
            raise ExtractionError('ocr_failed', 'Try another invoice.', 422)
        with patch.object(ocr, '_run_worker', side_effect=fail_read):
            with self.assertRaises(ExtractionError):
                ocr.read_document(upload(image_bytes(), filename='$(touch secret).png'))
        self.assertTrue(observed_paths)
        self.assertTrue(all(not path.exists() for path in observed_paths))
        self.assertEqual(observed_paths[0].name, 'input.json')

    @unittest.skipUnless(HAVE_PIL, 'Pillow is optional')
    def test_image_pixel_limit_before_inference(self):
        with patch.object(ocr, 'MAX_IMAGE_PIXELS', 100), \
                patch.object(ocr, '_read_image') as read:
            with self.assertRaises(ExtractionError) as caught:
                local_read(upload(image_bytes()))
        self.assertEqual(caught.exception.code, 'document_too_large')
        read.assert_not_called()

    @unittest.skipUnless(HAVE_PDF, 'PDF test dependencies are optional')
    def test_pdf_page_limit_rejects_entire_file(self):
        with patch.object(ocr, '_read_image') as read:
            with self.assertRaises(ExtractionError) as caught:
                ocr.read_document(upload(pdf_bytes(pages=11), 'application/pdf', 'invoices.pdf'))
        self.assertEqual(caught.exception.code, 'document_too_large')
        read.assert_not_called()

    @unittest.skipUnless(HAVE_PDF and HAVE_PIL, 'PDF and Pillow are optional')
    def test_scanned_pdf_cannot_succeed_with_only_header_when_ocr_missing(self):
        with patch.object(ocr, '_image_engine', return_value=None):
            with self.assertRaises(ExtractionError) as caught:
                local_read(upload(pdf_bytes(image=True), 'application/pdf', 'scan.pdf'))
        self.assertEqual(caught.exception.code, 'ocr_unavailable')


class RealLocalOCREngineTests(unittest.TestCase):
    @unittest.skipUnless(HAVE_PIL and HAVE_TESSERACT, 'Real English Tesseract is not installed')
    def test_real_english_image_recognition(self):
        with patch.dict(os.environ, {'RASAM_OCR_ENGINE': 'tesseract'}):
            result = ocr.read_document(upload(image_bytes()))
        self.assertEqual(result['engine'], 'tesseract')
        self.assertIn('INV-0042', result['text'])
        self.assertIn('115.00', result['text'])
        self.assertIn('Gulf Supply LLC', result['text'])
        if 'ara' not in ocr._tesseract_info()[1]:
            self.assertTrue(any('Arabic recognition is unavailable' in warning for warning in result['warnings']))

    @unittest.skipUnless(HAVE_PDF, 'PDF test dependencies are optional')
    def test_real_native_pdf_retains_page_breaks_without_ocr(self):
        with patch.object(ocr, '_read_image') as read:
            result = ocr.read_document(upload(pdf_bytes(pages=2), 'application/pdf', 'invoice.pdf'))
        read.assert_not_called()
        self.assertEqual(result['engine'], 'pdf-text')
        self.assertEqual(result['page_count'], 2)
        self.assertIn('--- Page 2 ---', result['text'])
        self.assertIn('Grand Total: 115.00', result['text'])

    @unittest.skipUnless(HAVE_PDF and HAVE_PIL and HAVE_TESSERACT, 'Real PDF OCR dependencies are optional')
    def test_real_scanned_pdf_reads_body_below_embedded_header(self):
        with patch.dict(os.environ, {'RASAM_OCR_ENGINE': 'tesseract'}):
            result = ocr.read_document(upload(pdf_bytes(image=True), 'application/pdf', 'scan.pdf'))
        self.assertEqual(result['engine'], 'tesseract')
        self.assertIn('INV-0042', result['text'])
        self.assertIn('115.00', result['text'])
        self.assertEqual(result['page_count'], 1)


if __name__ == '__main__':
    unittest.main()
