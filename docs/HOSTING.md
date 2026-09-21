# GitHub Pages hosting

The website is prepared on the `gh-pages` branch. That branch contains the contents of `site/` at its root, plus `.nojekyll` so GitHub serves the files directly.

## Activate the website

1. Open [Rasam → Settings → Pages](https://github.com/20SHA07/Rasam/settings/pages).
2. Under **Build and deployment**, set **Source** to **Deploy from a branch**.
3. Select the **gh-pages** branch and **/(root)** folder.
4. Click **Save**.

GitHub will build and deploy the site. When deployment succeeds, the Pages settings screen shows the live address:

**https://20SHA07.github.io/Rasam/**

The manual workbench preview is at:

**https://20SHA07.github.io/Rasam/workbench.html**

The address may return 404 until Pages is enabled and the first deployment finishes. Check the [Actions tab](https://github.com/20SHA07/Rasam/actions) for deployment progress or errors.

See [GitHub's publishing-source instructions](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).

## Update the website

The editable source is in `site/` on `main`. The publishing branch contains those same files at its root:

| Source on `main` | File on `gh-pages` |
| --- | --- |
| `site/index.html` | `index.html` |
| `site/styles.css` | `styles.css` |
| `site/script.js` | `script.js` |
| `site/favicon.svg` | `favicon.svg` |
| `site/workbench.html` | `workbench.html` |

After editing the source, copy the updated files to `gh-pages` and commit them there. Keep `.nojekyll` at the branch root. GitHub Pages publishes updates pushed to that branch; changing `main/site/` alone does not update the live site.

Only public website files belong on `gh-pages`. Customer invoices and API keys must stay outside the repository.

## What works online

The landing page, sample/manual invoice review, and Excel export work as static browser pages. Contact buttons open an email draft to `rasam@polsia.app`.

AI extraction runs through the separate local app in `workbench/`. GitHub Pages does not run the Python server. Publishing this website does not make a live AI endpoint available or require an API key in the page.
