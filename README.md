# Rasam

Invoice reading and review for GCC bookkeeping workflows. Rasam started with watching an accountant copy invoice details into Excel. The prototype reads documents, prepares editable drafts, and exports the records you approve.

**[Open the website](https://20SHA07.github.io/Rasam/)** · **[Try the manual workbench](https://20SHA07.github.io/Rasam/workbench.html)**

## Start the free reader

1. Download this repository with **Code → Download ZIP**, extract it, and open the `workbench` folder.
2. Install 64-bit Python, preferably Python 3.11. Run **Setup-OCR-Windows.bat** or **Setup-OCR-Mac.command** once. Setup downloads the OCR libraries and model files.
3. Run **Start-Rasam-Windows.bat** or **Start-Rasam-Mac.command**. Rasam opens at localhost; keep the terminal window open.
4. Upload one invoice, select **Read invoice**, review the source and suggested fields, then approve and export to Excel.

The default reader runs locally and needs no API key. It uses existing OCR models, including PaddleOCR's Arabic model, plus a conservative parser for labelled invoice fields. Setup requires internet access; local invoice reading does not send documents to an AI service.

For Linux, or to use a terminal:

```sh
cd workbench
python3.11 setup_ocr.py
.venv/bin/python start_rasam.py
```

Current Paddle installers support 64-bit Windows/Linux PCs and Apple Silicon Macs. See the [workbench setup guide](workbench/README.md) for platform notes, a lighter setup, and troubleshooting.

## Add free AI on your computer

Rasam can use **Ollama + Qwen3** to organize recognized text into invoice fields. This runs on your computer and needs no API key or paid plan.

1. Complete OCR setup above, then install [Ollama](https://ollama.com/download) and open it.
2. In Command Prompt on Windows or Terminal on Mac, download the model once:

   ```sh
   ollama pull qwen3:4b-instruct-2507-q4_K_M
   ```

3. Run **Start-Rasam-Local-AI-Windows.bat** or **Start-Rasam-Local-AI-Mac.command** from `workbench`.
4. Upload an invoice, click **Read invoice**, and review the draft before approving it.

The [model download](https://ollama.com/library/qwen3:4b-instruct-2507-q4_K_M) is about 2.5 GB; running it also needs working memory. Speed depends on your computer, and CPU reading can be slow. Initial software/model downloads need internet access. Invoice reading uses the local model, with no per-invoice API fee. The [full setup guide](workbench/README.md#free-local-ai-with-ollama) explains how to disable Ollama cloud features and troubleshoot setup.

## Optional cloud AI

After OCR setup, run the **Start-Rasam-Groq** launcher for your system. Enter your own Groq API key at the hidden terminal prompt. This sends the extracted text to Groq to organize it into invoice fields; it does not send the PDF or image. A blank key returns to local OCR.

Groq has a free plan with request and token limits. Rasam shows a local draft with a warning if the AI step fails or reaches a limit. Check your account's [current limits](https://console.groq.com/docs/rate-limits) and [data settings](https://console.groq.com/docs/your-data). The separate OpenAI reader remains an explicit, paid option.

## What works today

- PDF and image uploads, local text recognition, and optional AI extraction.
- Arabic and English field handling, with missing or ambiguous values left for review.
- Invoice issue date, printed VAT rate, and supplier VAT number / TRN alongside invoice amounts.
- Source documents and extracted text beside editable invoice details.
- Amount checks, duplicate warnings, required human approval, and Excel export.

Arabic/GCC reading accuracy has not been measured on a representative dataset. Rasam does not post journals to an ERP, provide tax clearance, or preserve an audit history across sessions. Export before closing or reloading the app.

Rasam does not yet learn from your invoice history. The next step is to store approved corrections separately for each company and use relevant examples when reading another invoice. Uploading files alone does not train a model. See the [invoice-learning plan](docs/INVOICE-LEARNING.md).

## Keep your Windows copy updated

Use a Git clone of this repository for automatic updates. A downloaded ZIP has no Git connection.

1. From your existing Rasam clone, run `git pull --ff-only` once to get the updater.
2. Open `scripts` and double-click **Enable-Auto-Update-Windows.bat**.
3. Leave Windows to check GitHub every five minutes while you are signed in and the computer is awake. It also checks when you sign in.

The updater applies new `main` commits only when your working copy has no local edits or commits of its own. Otherwise it pauses updates and records the reason. It does not upload, commit, or discard your work. Export any active invoice work, then restart Rasam to load updated server code.

Use **Disable-Auto-Update-Windows.bat** to turn it off. See the [automatic update guide](docs/AUTO-UPDATES.md) for setup, status, and limits. Enabling the task is a one-time action on your own Windows computer.

## Website and project files

GitHub Pages serves the landing page and manual preview. OCR and AI reading run through the local app; GitHub Pages cannot run its Python server.

| Path | Purpose |
| --- | --- |
| `site/` | Editable public website and manual workbench preview |
| `workbench/` | Local reader, setup, launchers, browser source, and tests |
| `docs/` | Hosting and invoice-learning guides |
| `scripts/build-landing.py` | Optional single-file landing-page export |

The `gh-pages` branch publishes the website. See the [hosting guide](docs/HOSTING.md) to update it. No customer invoices, training data, or API keys are included. All example invoices are fictional.
