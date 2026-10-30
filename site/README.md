# mdrestyler site

The static landing page and reference for mdrestyler, published by GitHub Pages at https://sagol.github.io/mdrestyler/. Everything here is plain files: no build step, no dependencies, and no third-party requests.

## Files

- `index.html`: the page. Semantic HTML with a strict Content-Security-Policy, Open Graph and Twitter card tags, JSON-LD (`WebSite`, `SoftwareApplication`, `SoftwareSourceCode`, `HowTo`, `FAQPage`), install tabs whose panels all show without JavaScript, the measures, the restyle procedure, the cross-restyle example with its results, the command reference, profiles and the copy guard, a section for AI agents, limits and an FAQ.
- `styles.css`: dark and light themes, focus styles, reduced motion, layouts down to 320 px. No external fonts.
- `app.js`: the theme toggle, ARIA tabs, copy buttons with a selection fallback and a live region, and the command filter. Loaded as a local file, as the CSP requires.
- `llms.txt`: the short index for LLMs, in the llmstxt.org format.
- `llms-full.txt`: one file with every command and flag, exit codes, profile files and schemas, the restyle procedure, the measures, the limits, and the verbatim `--help` of each command.
- `agents.json` and `.well-known/agent.json`: the capability manifest and its discovery pointer.
- `robots.txt`, `sitemap.xml`, `site.webmanifest`, `favicon.svg`, `og-image.svg`, `og-image.png` (1200x630, rendered from the SVG), `.nojekyll`.
- `validate.py`: checks the site against the checked-out code.
- `stage.py`: holds `PUBLIC_FILES`, the list of files that get published, and copies them into an empty folder.
- `deploy-gh-pages.sh`: publishes the committed site to the `gh-pages` branch.
- `github-pages-workflow.yml`: a workflow template for deploying with GitHub Actions. It is not installed.

Under the project path, crawlers read `https://sagol.github.io/robots.txt`, not this folder's `robots.txt`; it applies only if the site moves to a domain root. Submit `https://sagol.github.io/mdrestyler/sitemap.xml` to search consoles directly.

## Preview

From the repository root:

```bash
python3 -m http.server 8000 --bind 127.0.0.1 --directory site
```

Then open http://127.0.0.1:8000/.

## Validate

From the repository root, with Python 3.10 or later and nothing installed:

```bash
python3 site/validate.py
node --check site/app.js
bash -n site/deploy-gh-pages.sh
python3 -m unittest tests.test_skill
```

`validate.py` imports mdrestyler from `skills/mdrestyler/scripts` and checks:

- the version on the page, in JSON-LD, the manifests, the LLM files and the social image equals `mdrestyler.__version__`;
- every `mdrestyler COMMAND ...` example (in the page's code blocks and inline code, the LLM files, the manifests and the GitHub Action snippets) names a real command and real flags, read from the command's own parser; complete examples are also passed through the command's argument checks, with the work itself replaced, so nothing runs;
- every command has a row in the commands table, an entry in `agents.json` and a section in `llms-full.txt`, and every flag appears in `llms-full.txt`;
- local links, fragment ids, site URLs and links to files in this repository resolve;
- ARIA and copy targets exist, and each tab and its panel point at each other;
- JSON, JSON-LD, the sitemap and the SVGs parse, and `og-image.png` is 1200x630;
- the page makes no third-party request, has no inline script or style, and its CSP allows no remote origin;
- there is one `h1` and no heading level is skipped;
- the main color pairs in both themes keep a contrast of 4.5:1 or more;
- `stage.PUBLIC_FILES` exist, and no file names another product or a private path.

It does not fetch external URLs, check every claim in the prose, or test a screen reader. Repository links are checked against the working tree, so a link to a file that is not on `main` yet passes until it is merged.

Before a release, look at the page at 320, 390, 768 and 1280 px in both themes, and try the tabs with the keyboard, the copy buttons, the page without JavaScript, reduced motion and zoom.

## Update for a release

When `mdrestyler.__version__` changes, `validate.py` lists every place on the site that still shows the old version. Change them, re-render the social image from its SVG with any headless browser at a 1200x630 window, update `lastmod` in `sitemap.xml`, and validate again.

## Stage

```bash
python3 site/stage.py _site
```

The destination must be empty. Only `PUBLIC_FILES` are copied; this README, the scripts and the workflow template stay out. Both deployment methods use the same list.

## Publish to GitHub Pages

### With GitHub Actions

1. Copy `site/github-pages-workflow.yml` to `.github/workflows/pages.yml`. It uses commit-pinned actions, validates the site against the code, stages `_site/`, and deploys from `main` with deployment permissions kept to the deploy job. Pull requests validate and stage without publishing.
2. In the repository's Settings, Pages, Build and deployment, set Source to GitHub Actions.

### From the gh-pages branch

1. Commit `site/` and merge it to `main`.
2. Run, from a clean checkout:

   ```bash
   bash site/deploy-gh-pages.sh
   ```

   It needs Python 3.10 or later, git, tar and a git author identity. It refuses uncommitted changes in `site/`, more than one push URL, a push URL with credentials in it, and any destination other than `sagol/mdrestyler` on GitHub, over a plain HTTPS URL (credentials come from a helper or git's environment, never the URL) or SSH. It stages from the committed snapshot in a temporary index, creates no local branch, and pushes with `--force-with-lease`, so it replaces `gh-pages` only if the remote branch has not moved since it looked.
3. In the repository's Settings, Pages, Build and deployment, set Source to Deploy from a branch, with `gh-pages` and `/ (root)`.
