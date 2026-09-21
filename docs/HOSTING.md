# Hosting Rasam

Use GitHub to keep the code and Cloudflare Pages to host the landing page. The public files are all in `site/`.

## Cloudflare Pages setup

1. In your Cloudflare dashboard, open **Workers & Pages** and choose **Create application**.
2. Select **Pages**, then **Import an existing Git repository**.
3. Connect GitHub and select **20SHA07/Rasam**.
4. Use these settings:

| Setting | Value |
| --- | --- |
| Production branch | `main` |
| Framework preset | None |
| Root directory | Leave at repository root |
| Build command | `exit 0` |
| Build output directory | `site` |
| Environment variables | None |

5. Review the settings and deploy when ready to make the page public.

Cloudflare supplies the actual `pages.dev` address after deployment. A GitHub repository URL is a code page, not the live website address. No deployment or custom domain is created merely by adding this code to GitHub.

The `site/index.html` file must remain at the top of the output directory. It links to `styles.css`, `script.js`, `favicon.svg`, and `workbench.html` using relative paths, so the same files also work under a project subpath.

See [Cloudflare's static HTML deployment instructions](https://developers.cloudflare.com/pages/framework-guides/deploy-anything/).

## What about GitHub Pages?

GitHub Pages can serve static project websites. It cannot run the Python server or securely hold an API key for the browser. GitHub also restricts using Pages as free hosting to run an online business or commercial SaaS. Use a suitable application host for Rasam as a business rather than assuming Pages covers the whole product.

Sources: [What is GitHub Pages?](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages) and [GitHub Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits).

## AI hosting is a later step

The bundled workbench server intentionally listens only on your computer. It has no customer sign-in, company access controls, persistent database, or production operations setup. Leave it local while evaluating the prototype.

A future hosted app needs a server-side API key, authenticated users, company-scoped data access, controlled document storage, and a reviewed retention policy. Those components belong outside the static `site` folder. Real invoices and model-training files must not be committed to the public repository.

The current page's contact buttons open an email draft to `rasam@polsia.app`. They do not save submissions in a database. The static workbench does not offer a live AI endpoint.
