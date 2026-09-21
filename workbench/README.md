# Rasam v0.2: AI invoice reading

Rasam reads an invoice into a draft, shows its source alongside editable details, and exports only the invoices you approve. It is a local prototype, not a posted ledger or a tax-compliance system.

## Turn on AI reading

1. Download the repository ZIP and extract it, or clone the repository. Open the `workbench` folder.
2. With Python 3 installed, double-click **Start-Rasam-Windows.bat** on Windows or **Start-Rasam-Mac.command** on Mac. You can also open a terminal in the `workbench` folder and run `python3 start_rasam.py` (`py -3 start_rasam.py` on Windows).
3. Enter your OpenAI API key at the launcher's hidden terminal prompt. Characters do not appear while entering it. The key stays in the server process for this session and is not saved by Rasam. Leave it blank to use manual mode.
4. The launcher opens Rasam at localhost. The app reports **AI key configured**. Your first read tests whether the key and model are usable.
5. Upload one PDF or image and click **Read with AI**. Review the extracted values, missing fields, and warnings. Tick the review checkbox, approve, and export to Excel.

An OpenAI API account with usable billing/quota and model access is required. API usage charges apply. Create a key through the [official OpenAI API setup guide](https://developers.openai.com/api/docs/quickstart). Enter it only in your local launcher, never in a chat message or browser source code.

Keep the launcher window open while using the app. Press Ctrl+C to stop. Port 8000 is used when available; otherwise the launcher prints and opens another local port.

**The website preview and the preview inside ChatGPT cannot call the AI server.** AI reading works in the localhost app. Opening `Rasam.html` directly supports samples and manual entry, but does not connect to the server.

## What makes the reading smarter

- The model receives the original PDF or image, so it can use document layout alongside text.
- Instructions cover mixed Arabic and English, Arabic-Indic and Persian digits, and decimal/grouping separators.
- It distinguishes the supplier from the billed customer, the invoice number from purchase-order references, and the invoice date from the due date.
- Unclear or missing fields remain empty and appear in review notes. The reader is instructed not to invent tax amounts from a presumed country rate or calculate missing values just to balance the invoice.
- Net, tax, and total are independently checked. A mismatch blocks approval until you resolve it against the source.
- Extracted line items appear as reference detail. They are not yet individual accounting entries and are not exported as separate rows.
- Existing values are kept. If you edit while a reading is in progress, your edits remain intact and AI values appear as suggestions. A **Use value** button lets you apply each conflicting suggestion deliberately.
- A returned draft never approves itself. Re-reading or editing an invoice requires another human review.
- Files with multiple invoices are intended to be flagged for separation, not combined into one record. Split such documents before reading.

These are implemented instructions, validation rules, and review behaviors. They are not measured accuracy claims. Test representative invoices before relying on the extraction.

## Data and keys

Uploading adds a file to the browser session. Only **Read with AI** sends that selected file to the local server and then to OpenAI. The backend requests `store: false`; that request does not itself establish zero retention by the API provider. Rasam does not write invoice files or API keys to disk. The browser retains its working records until you close or reload the page, so export first.

The server listens on 127.0.0.1 and uses a session token plus host/origin checks. It serves only the app and its specific API routes. Keys, source files, and server code cannot be downloaded through it. This is a local development server, not a public hosted deployment.

## Supported workflow and limits

- PDF, JPEG, PNG, WebP; at most 20 MB per file and 50 files in the browser inbox.
- One invoice per AI request, up to two concurrent server requests.
- Supplier, invoice number, invoice date, currency, net, tax, and invoice total, plus optional user notes.
- Supported register currencies: SAR, AED, USD, EUR, GBP. Other currencies are flagged instead of being silently substituted.
- The register accepts non-negative amounts with up to two decimal places and a positive total. Credit notes and other structures need a future workflow. Extracted negative values are not silently changed into positive amounts.
- Up to 50 line items as supporting detail. Individual line editing, chart-of-accounts coding, reconciliation, and ERP posting are not implemented.
- Excel contains one row per approved invoice. Dates and amounts are typed cells. Origins distinguish samples, manual entries, and AI-assisted records reviewed by a person.
- No persistent sessions, user accounts, or multi-user audit system.

## Troubleshooting

**AI server is not connected:** run the included launcher, leave its window open, and use the localhost address it prints. A generic static-file server does not include AI reading.

**Add your AI key:** restart the launcher and enter it at the hidden prompt. Existing `OPENAI_API_KEY` environment configuration is also supported.

**Authentication, quota, or model error:** review your OpenAI API account and project access. The app keeps your file and manual edits so you can continue without a successful read.

**Timeout or poor image:** try a clearer photo or a smaller PDF with one invoice. Requests are not automatically retried, to avoid unexpected repeat API usage.

**Amounts do not add up:** compare the source for discounts, shipping, withholding, or multiple taxes. The app will not change the original amounts to force a match.

**Unclear date or currency:** supply the correct value after inspecting the original. No confidence score is presented as a guarantee.

## Development

There are no required third-party Python or browser libraries.

- `Rasam.html`: bundled browser app.
- `start_rasam.py`: local server and hidden-key startup.
- `rasam_ai.py`: document validation, model request, extraction instructions, structured schema, and result validation.
- `source/index.html`, `source/styles.css`, `source/app.js`: review interface and behavior.
- `source/ai-client.js`: browser-to-local-server connection. It contains no secret.
- `source/export.js`: standalone Excel writer.
- `source/build.py`: bundles the browser source.
- `tests/`: backend and frontend logic tests with mocked API responses.

Rebuild the browser app from the `workbench` folder:

```sh
python3 source/build.py Rasam.html
```

To rebuild both the local app and the public manual preview, run `python3 build_preview.py` from the `workbench` folder. The public preview disables all AI API requests, even when served from localhost.

Run the backend tests:

```sh
python3 -m unittest discover -s tests -p 'test_ai_server.py' -v
```

If Node.js is available, run the frontend tests:

```sh
node tests/test_ai_frontend.cjs
```

`OPENAI_MODEL` can override the default `gpt-4.1-mini` on the server. Use a model your project can access that supports document/image inputs and structured output. The default was checked against [official model documentation](https://developers.openai.com/api/docs/models/gpt-4.1-mini). The request follows the official [file-input](https://developers.openai.com/api/docs/guides/file-inputs), [image-input](https://developers.openai.com/api/docs/guides/images-vision), and [structured-output](https://developers.openai.com/api/docs/guides/structured-outputs) guidance.

## Verification status

All 36 automated checks passed: 16 backend tests and 20 frontend/bridge tests. They cover application behavior and server contracts with simulated AI responses; they do not measure AI reading accuracy. No live OpenAI extraction was run because this workspace has no configured API key. Full browser rendering, native downloads, and mobile layout remain unverified because a browser binary was unavailable in the build environment. The earlier invoice-review logic and generated Excel files were checked separately.
