# Rasam: free local invoice reading

Rasam reads an invoice into an editable draft, shows the source and recognized text, and exports only the records you approve. The default reader runs on your computer without an API key.

## First setup

1. Download and extract the repository ZIP, then open `workbench`. If you downloaded the standalone starter ZIP, its extracted folder is the workbench.
2. Install **64-bit Python 3.11** from [python.org](https://www.python.org/downloads/). Python 3.10 to 3.13 are accepted by the setup script.
3. Double-click **Setup-OCR-Windows.bat** or **Setup-OCR-Mac.command**. It creates a `.venv` folder, installs CPU OCR libraries, and downloads the public OCR model files. Keep internet access available and wait for **Setup finished**.
4. Double-click **Start-Rasam-Windows.bat** or **Start-Rasam-Mac.command**. The launcher opens the localhost app. Keep its terminal window open.
5. Upload one invoice, click **Read invoice**, and compare every suggested field with the source. Resolve warnings, tick the review checkbox, approve, and export to Excel.

No key is requested by the default launcher. Port 8000 is used when available; otherwise Rasam opens another local port. Press Ctrl+C in the terminal to stop the server. Export your records before closing or reloading the page.

On Linux, or from a terminal in the workbench folder:

```sh
python3.11 setup_ocr.py
.venv/bin/python start_rasam.py --provider ocr
```

On Windows, the equivalent commands are:

```bat
py -3.11 setup_ocr.py
.venv\Scripts\python.exe start_rasam.py --provider ocr
```

Current Paddle CPU packages support 64-bit x86_64 Windows/Linux and arm64 Apple Silicon Macs. Intel Macs need the alternative below. See the official [Windows](https://www.paddlepaddle.org.cn/documentation/docs/en/install/pip/windows-pip_en.html), [Linux](https://www.paddlepaddle.org.cn/documentation/docs/en/install/pip/linux-pip_en.html), and [macOS](https://www.paddlepaddle.org.cn/documentation/docs/en/install/pip/macos-pip_en.html) installation notes if a package fails to install. Hardware and Python compatibility can vary; the setup script reports failures without claiming the reader is ready.

If a Mac does not open a `.command` launcher, use the terminal commands above from the extracted folder.

## Optional Groq AI

Local OCR provides the text. Groq can help turn that text into invoice fields, especially when labels and layout are less consistent.

1. Create your own Groq account and API key through the [Groq console](https://console.groq.com/keys).
2. After OCR setup, run **Start-Rasam-Groq-Windows.bat** or **Start-Rasam-Groq-Mac.command**.
3. Enter the key at the hidden terminal prompt. Characters do not appear while entering it. Leave it blank to return to local OCR.
4. Click **Read invoice** in the app. The status identifies the selected provider; the returned draft identifies what actually read the invoice.

The terminal equivalent is `.venv/bin/python start_rasam.py --provider groq`, or `.venv\Scripts\python.exe start_rasam.py --provider groq` on Windows. Existing `GROQ_API_KEY` environment configuration also works. Rasam does not save a key entered at the prompt.

Groq receives **extracted text only**, which can still contain invoice details and personal information. Review your organization's data policy and Groq's [data controls](https://console.groq.com/docs/your-data) before sending business invoices. Groq documents limited reliability/abuse retention and settings to opt out; Rasam does not configure those settings for you.

Groq's free plan has [request and token limits](https://console.groq.com/docs/rate-limits). It is not unlimited, and account limits can differ. If the request fails, is rate-limited, or exceeds Rasam's text limit, the app shows a local OCR draft with a warning. It does not switch to a paid provider. No retry runs automatically.

The default model is `qwen/qwen3.8-27b`; `GROQ_MODEL` can override it. The integration uses JSON mode followed by local schema and amount checks. That improves output structure but cannot guarantee correct invoice interpretation.

## How the free reader works

Rasam first extracts usable embedded text from text-only PDFs. Images and scanned pages use local PaddleOCR with its [Arabic PP-OCRv5 recognition model](https://huggingface.co/PaddlePaddle/arabic_PP-OCRv5_mobile_rec). An installed Tesseract can act as a fallback. The app shows which engine was used and warns if its Arabic language support is missing.

Without an AI key, a conservative parser looks for explicit Arabic/English labels, invoice references, dates, currencies, and amounts. Ambiguous values stay empty. It does not guess a country tax rate or calculate a missing amount just to balance the invoice. It does not extract line items in local-only mode.

Optional Groq organizes the OCR text. The separate OpenAI option reads the original image or PDF. Missing and uncertain fields remain review items. Existing edits are preserved if a read finishes while you are editing; conflicting suggestions have a **Use value** button. Reading or editing a record always requires another human review before approval.

These are implemented behaviors, not measured accuracy claims. This version uses existing models and does not train a new model from your uploads. Company-specific learning from approved corrections remains a [planned feature](https://github.com/20SHA07/Rasam/blob/main/docs/INVOICE-LEARNING.md).

## Lighter setup and Tesseract

For text-only PDFs, or a computer where Paddle cannot be installed, run:

```sh
python3.11 setup_ocr.py --basic
```

This installs PDFium and Pillow into `.venv`. Text-only PDFs can then be read locally. Images and scans additionally require a separate [Tesseract installation](https://tesseract-ocr.github.io/tessdoc/Installation.html) and its English (`eng`) and Arabic (`ara`) language packs. The command `tesseract --list-langs` should show both. Rasam checks the installed languages and does not silently claim Arabic support when the pack is absent.

Setup normally downloads Paddle models in advance. If that download was interrupted, run `.venv/bin/python rasam_ocr.py --download-models` on Mac/Linux, or `.venv\Scripts\python.exe rasam_ocr.py --download-models` on Windows, then restart Rasam. This downloads public model weights without using an invoice.

## Data and limits

Uploading adds a file to your browser session. **Read invoice** sends the selected file to the local server. In local mode, recognition and parsing stay on your computer. Temporary files are created for reading and cleaned up afterward. Downloaded OCR packages and model caches remain on your computer.

The server listens only on `127.0.0.1`, with a session token and host/origin checks. It serves the app and its API routes, not keys or arbitrary files. It is intended for local use, not public hosting. The GitHub Pages and ChatGPT previews support samples/manual entry and Excel export; they cannot run this Python reader.

| Limit | Current behavior |
| --- | --- |
| Uploads | PDF, JPEG, PNG, WebP; 20 MB per file; 50 files in the browser inbox |
| Local reading | One invoice per file, at most 10 PDF pages, 20 megapixels per image, 60,000 recognized characters |
| Reading time | Local OCR stops after about 120 seconds; the optional Groq step can take another 90 seconds |
| Groq input | At most 18,000 extracted characters; longer documents fall back to the local draft |
| Register | Supplier, invoice number/date, currency, net, tax, total, and optional notes |
| Currencies | SAR, AED, USD, EUR, GBP; other currencies need manual handling |
| Amounts | Non-negative, up to two decimal places, with a positive total; credit notes need a future workflow |
| Excel | One row per approved invoice, typed dates/amounts, and source labels distinguishing OCR, AI, manual, and sample records |

AI line items, when returned, are reference detail only and are not separate exported entries. Chart-of-accounts coding, ERP posting, tax clearance, saved sessions, and multi-user audit history are not implemented.

## Existing OpenAI option

Run `.venv/bin/python start_rasam.py --provider openai` or `.venv\Scripts\python.exe start_rasam.py --provider openai` on Windows. Enter an OpenAI API key at the hidden prompt, or configure `OPENAI_API_KEY` in your environment. This option sends the selected original file to OpenAI and requires usable API quota; API charges apply. It is never selected by the standard free-reader launcher.

The default model is `gpt-4.1-mini`, overridable with `OPENAI_MODEL`. The backend requests `store: false`, which does not establish zero retention by the provider. Never put any API key in chat, browser code, or this repository.

## Troubleshooting

**Reader is unavailable:** run OCR setup, then restart the included launcher. A static file server and a directly opened `Rasam.html` cannot provide reading APIs.

**Only text PDFs are available:** PDF support is installed but an image OCR engine is missing. Finish Paddle setup, or install Tesseract and its language packs.

**Setup or model download failed:** read the last installer error, check internet access and Python/platform compatibility, then rerun setup. Use `--basic` if Paddle is unsupported on your machine.

**Slow or unreadable document:** try one clear, upright invoice photo or a smaller PDF. Split files containing several invoices. The app keeps your manual edits when reading fails.

**Amounts do not add up:** inspect the source for discounts, shipping, withholding, or multiple taxes. Rasam will not alter the numbers to force a match.

## Development and verification

`start_rasam.py` hosts the local app. `rasam_ocr.py` reads documents; `rasam_text.py` prepares local drafts; `rasam_groq.py` handles optional text-based AI; `rasam_ai.py` contains the shared schema and existing OpenAI reader. Browser source is in `source/`.

Rebuild the local app and static preview:

```sh
python3 build_preview.py
```

Run the automated checks:

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
node tests/test_ai_frontend.cjs
```

Backend and frontend checks cover reading contracts, validation, fallback behavior, review safeguards, and exports. A generated English invoice was also read through local Tesseract and the localhost API. Paddle/Arabic model inference and live Groq/OpenAI requests have not been tested in the build environment. No representative GCC accuracy benchmark or full browser rendering test has been completed.
