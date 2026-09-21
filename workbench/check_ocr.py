"""Diagnose PaddleOCR locally using only a generated, fictional invoice image."""
from argparse import ArgumentParser
from importlib.metadata import PackageNotFoundError, version
import os
from pathlib import Path
import platform
import sys
from tempfile import TemporaryDirectory
import traceback


def _sample_image(path):
    from PIL import Image, ImageDraw, ImageFont

    lines = (
        'TEST INVOICE - FICTIONAL SAMPLE',
        'Supplier: Rasam Test Supplies',
        'Invoice Number: TEST-0042',
        'Invoice Date: 2026-01-15',
        'Currency: SAR',
        'Net Amount: 100.00',
        'VAT Amount: 15.00',
        'Grand Total: 115.00',
    )
    with Image.new('RGB', (1400, 1000), 'white') as picture:
        draw = ImageDraw.Draw(picture)
        font = ImageFont.load_default(size=40)
        for row, text in enumerate(lines):
            draw.text((60, 60 + row * 100), text, font=font, fill='black')
        picture.save(path, format='PNG')


def main(argv=None):
    parser = ArgumentParser(description=__doc__)
    parser.parse_args(argv)  # Deliberately accepts no invoice paths or uploads.
    print('Rasam local PaddleOCR check', flush=True)
    print('This reads a generated sample only, never your invoice files.', flush=True)
    print('Loading the model may download public model weights.', flush=True)
    print('This checks that OCR runs. The sample is not an accuracy benchmark.', flush=True)
    stage = 'Check environment'
    try:
        print('\n[1/4] Check environment', flush=True)
        print('Python executable:', sys.executable, flush=True)
        print('Python version:', sys.version.replace('\n', ' '), flush=True)
        print('Platform:', platform.platform(), platform.machine(), flush=True)
        for package in ('Pillow', 'paddlepaddle', 'paddleocr', 'paddlex', 'pypdfium2'):
            try:
                installed = version(package)
            except PackageNotFoundError:
                installed = 'NOT INSTALLED'
            print('{}: {}'.format(package, installed), flush=True)
        print('RASAM_OCR_ENGINE:', os.environ.get('RASAM_OCR_ENGINE', 'auto (default)'), flush=True)
        import rasam_ocr
        print('Detected OCR status:', rasam_ocr.local_ocr_status(), flush=True)
        print('This diagnostic tests PaddleOCR directly, regardless of the selected engine.', flush=True)

        stage = 'Load PaddleOCR model'
        print('\n[2/4] Load PaddleOCR model', flush=True)
        rasam_ocr._load_paddle()

        with TemporaryDirectory(prefix='rasam-ocr-check-') as directory:
            stage = 'Create generated sample'
            print('\n[3/4] Create generated sample', flush=True)
            path = Path(directory) / 'fictional-invoice.png'
            _sample_image(path)

            stage = 'Read generated sample'
            print('\n[4/4] Read generated sample', flush=True)
            text, _warnings = rasam_ocr._paddle_text(path)
            count = len(text.strip())
            print('Recognized characters:', count, flush=True)
            if not count:
                raise RuntimeError('PaddleOCR returned no text for the generated sample.')

        print('\nSUCCESS: PaddleOCR loaded and read the generated image.', flush=True)
        print('Restart Rasam and review every extracted invoice field.', flush=True)
        return 0
    except Exception:
        print('\nFAILED at stage: {}'.format(stage), flush=True)
        traceback.print_exc(file=sys.stdout)
        print('Copy this output so we can identify the specific OCR error.', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
