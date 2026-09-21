# GitHub Pages hosting

Rasam is published at **[20SHA07.github.io/Rasam](https://20SHA07.github.io/Rasam/)**. The [manual workbench preview](https://20SHA07.github.io/Rasam/workbench.html) is available there too.

The publishing source is the `gh-pages` branch, with website files at its root. `.nojekyll` tells GitHub to serve those files directly. The [Actions tab](https://github.com/20SHA07/Rasam/actions) shows deployment progress after an update.

## Update the website

Edit the source in `site/` on `main`, then copy changed files into the publishing branch:

| Source on `main` | File on `gh-pages` |
| --- | --- |
| `site/index.html` | `index.html` |
| `site/styles.css` | `styles.css` |
| `site/script.js` | `script.js` |
| `site/favicon.svg` | `favicon.svg` |
| `site/workbench.html` | `workbench.html` |

Keep `.nojekyll` at the branch root. Changes to `main/site/` alone do not update the live website. To rebuild the workbench preview from its browser source, run `python3 build_preview.py` in `workbench/` before publishing.

For a local website preview, run this from the repository folder:

```sh
python3 -m http.server 8080 --bind 127.0.0.1 --directory site
```

Then open [localhost:8080](http://localhost:8080). On Windows, replace `python3` with `py -3`.

If you fork the repository, select **Deploy from a branch → gh-pages → /(root)** in the fork's **Settings → Pages**. See [GitHub's publishing-source instructions](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).

## What works online

The landing page, sample/manual invoice review, and Excel export work as static browser pages. Feedback buttons open the public Rasam GitHub issue form.

OCR and optional Groq/OpenAI reading run through the separate [local app](../workbench/README.md). GitHub Pages cannot run its Python server, and the public preview disables reading requests. Never put an API key in website code. Customer invoices and keys must stay outside the repository.

The local server is designed for one computer. A future public reader will need a separate backend with authentication and suitable document storage.
