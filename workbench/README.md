# Rasam: free local invoice reading

Rasam reads an invoice into an editable draft, shows the source and recognized text, and exports only the records you approve. Local OCR and optional local AI both run on your computer without an API key.

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

## Free local AI with Ollama

Ollama runs a downloaded Qwen3 model on your computer. Rasam sends recognized text to that local model to suggest invoice fields. There is no API fee or subscription for this option; your computer supplies the processing power and electricity.

1. Complete **First setup** above so Rasam can recognize invoice text.
2. Install [Ollama](https://ollama.com/download), then open the Ollama app.
3. Open **Command Prompt** on Windows or **Terminal** on Mac. Paste this command and wait for the download to finish:

   ```sh
   ollama pull qwen3:4b-instruct-2507-q4_K_M
   ```

4. Double-click **Start-Rasam-Local-AI-Windows.bat** or **Start-Rasam-Local-AI-Mac.command** in the Rasam folder. Keep Ollama and the Rasam terminal running.
5. In the browser, upload one invoice and click **Read invoice**. Check the suggested fields against the source before approving and exporting.

The [selected model](https://ollama.com/library/qwen3:4b-instruct-2507-q4_K_M) has an Apache 2.0 license and a download size of about **2.5 GB**. This is the model file size, not its RAM requirement. The model, OCR engine, and their working memory must fit your computer. CPU processing can be slow; performance depends on your hardware and the document. Model downloads require internet access, but local invoice reading does not require an AI service or account.

The terminal equivalent, from the Rasam folder, is:

```sh
.venv/bin/python start_rasam.py --provider ollama
```

On Windows:

```bat
.venv\Scripts\python.exe start_rasam.py --provider ollama
```

Rasam connects only to Ollama at `127.0.0.1:11434`. It checks that the model is installed locally and rejects cloud models. Reading an invoice never starts a model download or switches to a cloud provider. If the local AI request fails, the app keeps the local OCR draft and shows a warning.

The default model is `qwen3:4b-instruct-2507-q4_K_M`. Advanced users can select another installed local Qwen3 text model with `OLLAMA_MODEL`; Rasam requires local GGUF model metadata, the Qwen3 architecture, and support for a context of at least 16,384 tokens. Smaller supported Qwen3 models need careful invoice testing before use.

To disable Ollama's cloud features for the Ollama app itself, add `"disable_ollama_cloud": true` to its `server.json` settings and restart Ollama. The file is `%USERPROFILE%\.ollama\server.json` on Windows or `~/.ollama/server.json` on Mac/Linux. If it does not exist, create it with:

```json
{
  "disable_ollama_cloud": true
}
```

If the file already has settings, keep them and add this property. Ollama also supports `OLLAMA_NO_CLOUD=1`, but it must be set before the Ollama server starts. Rasam's launcher cannot change an Ollama app that is already running. See [Ollama's local-only configuration](https://docs.ollama.com/faq#how-do-i-disable-ollama-cloud-features).

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

With the default OCR reader, a conservative parser looks for explicit Arabic/English labels, invoice references, dates, currencies, and amounts. Ambiguous values stay empty. It does not guess a country tax rate or calculate a missing amount just to balance the invoice. This basic parser does not extract line items.

Optional Ollama organizes the OCR text locally. Groq sends that text to its cloud service, while the separate OpenAI option sends the original image or PDF. Missing and uncertain fields remain review items. Existing edits are preserved if a read finishes while you are editing; conflicting suggestions have a **Use value** button. Reading or editing a record always requires another human review before approval.

These are implemented behaviors, not measured accuracy claims. This version uses existing models and does not train a new model from your uploads. Company-specific learning from approved corrections remains a [planned feature](https://github.com/20SHA07/Rasam/blob/main/docs/INVOICE-LEARNING.md).

## Lighter setup and Tesseract

For text-only PDFs, or a computer where Paddle cannot be installed, run:

```sh
python3.11 setup_ocr.py --basic
```

This installs PDFium and Pillow into `.venv`. Text-only PDFs can then be read locally. Images and scans additionally require a separate [Tesseract installation](https://tesseract-ocr.github.io/tessdoc/Installation.html) and its English (`eng`) and Arabic (`ara`) language packs. The command `tesseract --list-langs` should show both. Rasam checks the installed languages and does not silently claim Arabic support when the pack is absent.

Setup normally downloads Paddle models in advance. If that download was interrupted, run `.venv/bin/python rasam_ocr.py --download-models` on Mac/Linux, or `.venv\Scripts\python.exe rasam_ocr.py --download-models` on Windows, then restart Rasam. This downloads public model weights without using an invoice.

## Data and limits

Uploading adds a file to your browser session. **Read invoice** sends the selected file to the local server. With OCR or Ollama selected, recognition and invoice interpretation stay on your computer. Temporary files are created for reading and cleaned up afterward. Downloaded OCR packages and model caches remain on your computer.

The server listens only on `127.0.0.1`, with a session token and host/origin checks. It serves the app and its API routes, not keys or arbitrary files. It is intended for local use, not public hosting. The GitHub Pages and ChatGPT previews support samples/manual entry and Excel export; they cannot run this Python reader.

| Limit | Current behavior |
| --- | --- |
| Uploads | PDF, JPEG, PNG, WebP; 20 MB per file; 50 files in the browser inbox |
| Local reading | One invoice per file, at most 10 PDF pages, 20 megapixels per image, 60,000 recognized characters |
| Reading time | Local OCR stops after about 120 seconds; Ollama can take another 180 seconds, or Groq another 90 seconds |
| Ollama input | At most 7,424 UTF-8 bytes of recognized text; Arabic characters take multiple bytes. Longer documents keep the complete local OCR draft with a warning |
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

**Ollama is unavailable:** open the Ollama app, then restart the Local-AI launcher. Rasam expects its local service on port 11434. If the app is unavailable, `ollama serve` starts the service from a separate terminal; leave that terminal open.

**Local AI model is missing:** run the exact `ollama pull` command above, wait for it to finish, then restart Rasam. `ollama list` shows downloaded models. The ordinary **Start-Rasam** launcher still works with local OCR while you set up the model.

**Local AI runs out of memory or takes too long:** close other heavy applications and try one short invoice. Rasam falls back to its OCR draft if the AI request fails. A smaller supported Qwen3 model may be faster but can make more mistakes; compare output with the invoice before relying on it.

**Setup or model download failed:** read the last installer error, check internet access and Python/platform compatibility, then rerun setup. Use `--basic` if Paddle is unsupported on your machine.

**PaddleOCR could not load or read an image:** from the workbench folder, run `.\.venv\Scripts\python.exe check_ocr.py` on Windows, or `.venv/bin/python check_ocr.py` on Mac/Linux. The diagnostic prints package versions and the underlying error, loads the models, and tests reading a generated sample image. Loading may download public model weights. It does not read your invoices. Share the failed stage and traceback when requesting help. A successful check confirms that the sample can be processed; it is not an invoice accuracy benchmark.

**Slow or unreadable document:** try one clear, upright invoice photo or a smaller PDF. Split files containing several invoices. The app keeps your manual edits when reading fails.

**Amounts do not add up:** inspect the source for discounts, shipping, withholding, or multiple taxes. Rasam will not alter the numbers to force a match.

## Development and verification

`start_rasam.py` hosts the local app. `rasam_ocr.py` reads documents; `rasam_text.py` prepares local drafts; `rasam_ollama.py` calls the optional local model; `rasam_groq.py` handles optional cloud text extraction; `rasam_ai.py` contains the shared schema and existing OpenAI reader. Browser source is in `source/`.

Rebuild the local app and static preview:

```sh
python3 build_preview.py
```

Run the automated checks:

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
node tests/test_ai_frontend.cjs
```

Backend and frontend checks cover reading contracts, validation, fallback behavior, review safeguards, and exports. A generated English invoice was also read through local Tesseract and the localhost API. The Ollama adapter is checked with simulated local responses; actual Qwen inference, Paddle/Arabic model inference, and live Groq/OpenAI requests have not been tested in the build environment. No representative GCC accuracy benchmark or full browser rendering test has been completed.
