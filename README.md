# Rasam

Invoice reading and review for GCC bookkeeping workflows. This repository contains the Rasam landing page and a working local prototype inspired by watching an accountant copy invoice details into Excel.

## Open the website

GitHub Pages address: **[20SHA07.github.io/Rasam](https://20SHA07.github.io/Rasam/)**.

For first-time activation, select the `gh-pages` branch and `/(root)` in [Settings → Pages](https://github.com/20SHA07/Rasam/settings/pages), then save. See [the hosting guide](docs/HOSTING.md).

You can also open `site/index.html` locally in a browser. No installation or build is required.

For a localhost preview, run this from the repository folder:

```sh
python3 -m http.server 8080 --bind 127.0.0.1 --directory site
```

Then open **http://localhost:8080**. On Windows, use `py -3` instead of `python3`.

The **Try workbench** button opens a static preview with sample invoices, manual editing, review, and Excel export. AI reading is available through the local app below.

## Use the AI reader

Open the `workbench` folder and run its Windows or Mac launcher, or:

```sh
cd workbench
python3 start_rasam.py
```

The launcher asks for your OpenAI API key in the terminal and opens the local app. Entering a key is optional; leave it blank for manual mode. An API account with usable quota is required for AI reading and API charges apply. Never add your key to this repository.

See [workbench/README.md](workbench/README.md) for supported files, setup, data handling, and known limits.

## What works today

- PDF and image uploads, one invoice per reading.
- AI-assisted extraction designed for Arabic and English invoices, with uncertain fields left for review.
- Source documents alongside editable invoice details.
- Amount checks, duplicate warnings, and required human approval.
- Excel export of approved invoice records.

The workbench is a prototype. It does not post journals to an ERP, provide tax clearance, learn automatically from previous invoices, or save an audit history across sessions. Arabic/GCC extraction accuracy has not yet been measured on a representative dataset.

## Learning from invoices

Rasam can be extended to remember approved corrections for each company and retrieve relevant examples for the next invoice. That is the proposed next step, not a feature already running. Raw uploads alone do not train a model. Start with reviewed examples from one company before broadening across GCC countries.

See [the invoice-learning plan](docs/INVOICE-LEARNING.md).

## Put the landing page online

The `gh-pages` branch contains the public website, ready for GitHub Pages. [The hosting guide](docs/HOSTING.md) covers activation and updates.

The editable website source lives in `main/site/`. Publish changes to the `gh-pages` branch to update the live site.

The local Python AI server is a separate component and is not suitable for public deployment as it stands. Publishing the landing page does not deploy the AI reader.

## Project layout

| Path | Purpose |
| --- | --- |
| `site/` | Public landing page and manual workbench preview |
| `workbench/` | Local AI app, launchers, source, and tests |
| `docs/` | Hosting and invoice-learning plans |
| `scripts/build-landing.py` | Optional single-file landing-page export |

No customer invoices, training data, or API keys are included. All example invoices are fictional.
