"""Explicit, one-time local OCR setup. Uses only the standard library to start."""
from argparse import ArgumentParser
import os
from pathlib import Path
import platform
import struct
import subprocess
import sys
import venv


ROOT = Path(__file__).resolve().parent
ENV = ROOT / '.venv'
PADDLE_INDEX = 'https://www.paddlepaddle.org.cn/packages/stable/cpu/'
BASIC_REQUIREMENTS = ['pypdfium2>=4.30,<6', 'Pillow>=10.4,<13']


def run(command):
    subprocess.run(command, check=True, cwd=str(ROOT))


def main():
    parser = ArgumentParser(description='Install Rasam OCR libraries in workbench/.venv.')
    parser.add_argument('--basic', action='store_true',
                        help='Install PDF/image support only; use an existing Tesseract installation for OCR.')
    args = parser.parse_args()
    if sys.version_info < (3, 10) or sys.version_info >= (3, 14):
        print('Use 64-bit Python 3.10 to 3.13 for this setup. Python 3.11 is recommended.')
        return 1
    if struct.calcsize('P') * 8 != 64:
        print('Install 64-bit Python before running OCR setup.')
        return 1

    print('Installing Rasam OCR libraries into: {}'.format(ENV), flush=True)
    print('This downloads packages and public model files. It does not upload invoices or ask for an API key.', flush=True)
    python = ENV / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    try:
        if not python.is_file():
            venv.EnvBuilder(with_pip=True).create(str(ENV))
        run([str(python), '-m', 'pip', 'install', '--upgrade', 'pip'])
        run([str(python), '-m', 'pip', 'install', *BASIC_REQUIREMENTS])
        if not args.basic:
            machine = platform.machine().lower()
            if platform.system() == 'Darwin' and machine not in ('arm64', 'aarch64'):
                print('\nPDF support is installed. Current Paddle CPU wheels require an Apple Silicon Mac.')
                print('For an Intel Mac, use the Tesseract option in README.md, then start Rasam.')
                return 1
            run([str(python), '-m', 'pip', 'install', 'paddlepaddle>=3.0,<4',
                 '--index-url', PADDLE_INDEX])
            run([str(python), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements-ocr.txt')])
            run([str(python), '-c', 'import paddle; import paddleocr; import pypdfium2; import PIL; print("OCR libraries imported successfully.")'])
            print('\nDownloading the Arabic/English OCR models. This may take several minutes.', flush=True)
            run([str(python), str(ROOT / 'rasam_ocr.py'), '--download-models'])
        else:
            run([str(python), '-c', 'import pypdfium2; import PIL; print("PDF and image libraries imported successfully.")'])
    except (subprocess.CalledProcessError, OSError) as error:
        print('\nSetup did not finish. Your invoice files have not been changed.')
        print('Read the installer error above and the platform notes in README.md.')
        print('Try this again with 64-bit Python 3.11, or use: python setup_ocr.py --basic')
        if isinstance(error, OSError):
            print('Setup could not start a required program: {}'.format(error))
        return 1
    print('\nSetup finished. Run the Start-Rasam launcher for your system.')
    if args.basic:
        print('Text-only PDFs work now. Images and scans need a separate Tesseract installation.')
    else:
        print('OCR models are ready to load. Review every result against the original invoice.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
