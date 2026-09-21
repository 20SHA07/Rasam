# Learning from GCC invoices

Rasam can be extended to remember an accountant's approved corrections and use relevant examples when reading the next invoice. This document describes the next development stage. The current app does not save corrections or train itself.

## Start with your dad's workflow

Begin with one company and a representative set of invoices that the company permits you to use. A practical pilot might start with 50 to 100 invoices, including Arabic, English, mixed script, PDFs, scans, and phone photos. That number is a starting suggestion, not an accuracy guarantee or a model-training requirement.

For each invoice, ask the accountant to check the supplier, invoice number, date, currency, net, tax, and total. If accounting suggestions are the goal, also collect the company's chart of accounts and the correct GL account and cost center. The current app does not yet support those accounting fields.

Keep real invoices and their corrected answers in private storage outside this public repository. For discussing examples, redact account numbers and personal information that are not needed for the task.

## Build correction memory first

1. Give every company a separate identity and enforce access on the server.
2. Save the original draft, the approved correction, the reviewer, and the source reference in a database.
3. Retrieve a few approved examples for the same company and a similar supplier or invoice layout.
4. Use those examples to suggest how to read or categorize the new invoice.
5. Show the suggestion beside its source and require human approval.

For example, an accountant may repeatedly code a particular type of stationery purchase to office supplies. Rasam could offer that reviewed category again for a similar purchase at the same company. A different purchase from the same supplier may need a different category, so supplier memory must remain a suggestion.

Every new invoice needs its own number, date, and amounts. These values must never be copied from an old example. Corrections must be replaceable or removable, and one company's examples must never appear in another company's results.

This approach is application memory, not retraining the model's weights. A small database with reliable company and supplier matching can come before vector search. If semantic retrieval becomes useful, OpenAI's [retrieval documentation](https://developers.openai.com/api/docs/guides/retrieval) describes example-search components; access control remains the application's responsibility.

## Check whether it actually improves

Reserve invoices that the system never sees as examples. Compare the current reader with the memory-assisted version on those same unseen invoices.

Measure correct supplier and invoice identification, date and amount errors, missing-field detection, incorrect suggestions, and the time an accountant needs to correct a draft. Test later invoices from familiar suppliers and separately test unfamiliar suppliers and layouts. Measure extraction and accounting-category suggestions separately.

The GCC is not one document format. Start with the countries, currencies, and suppliers the first customer uses. The present register supports SAR and AED, plus USD, EUR, and GBP. Other GCC currencies, amounts requiring more than two decimal places, and credit notes need additional implementation before a wider pilot.

## When to consider model training

Consider a separate training project only after reviewed examples and held-out tests show a recurring problem that prompting and example retrieval do not solve. Training needs intentional input/output examples, evaluation, and a suitable available model provider. Uploading more invoices alone does not perform training.

Do not make OpenAI fine-tuning a dependency for a new Rasam account: its current [supervised fine-tuning documentation](https://developers.openai.com/api/docs/guides/supervised-fine-tuning) says the self-service platform is winding down and unavailable to new users. Correction memory can be built independently of that service.

## Current status

No real GCC invoice dataset has been supplied or evaluated. The current extraction instructions cover Arabic and English, but GCC-wide accuracy, compliance certification, calibrated confidence scores, unattended accounting, and measured time savings have not been demonstrated.
