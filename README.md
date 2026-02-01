# ABGViewer Content Hosting (GitHub Pages)

This repository is designed to **host ABG (Airport Briefing Guide) PDFs** and a **`manifest.json`** on **GitHub Pages** so the ABGViewer iPad app can:

- Fetch a manifest from a **stable URL**
- Validate integrity with **SHA-256 (ground truth)**
- Download only PDFs that changed (size/sha mismatch)
- Work offline using the app’s cached manifest + cached PDFs

It is intentionally **100% free**:
- GitHub repo (public)
- GitHub Pages (public)

No paid hosting/CDN/backends.

## Published URL layout

GitHub Pages will publish the contents of the `docs/` folder.

- `docs/manifest.json` → stable manifest URL
- `docs/pdfs/<IATA>/<SHA256>.pdf` → immutable, versioned PDFs
- `docs/manifests/manifest-<timestamp>.json` → archived manifests for rollback

Example (replace with your repo):
- `https://<username>.github.io/<repo>/manifest.json`
- `https://<username>.github.io/<repo>/pdfs/JFK/2f1c...e9.pdf`

## Why PDFs are stored at SHA-based URLs

GitHub Pages (and intermediate caches) may cache content. **If the same URL is reused for a changed file**, some clients can see stale content.

By publishing PDFs at **content-addressed URLs** (`.../<sha256>.pdf`), each change produces a **new URL**. That makes PDF caching safe and reliable.

## GitHub Pages caching note (important)

GitHub Pages does not let you set custom cache headers. In practice, **`manifest.json` can be cached** by browsers and intermediary caches.

ABGViewer mitigates this by:
- Fetching the manifest with an **ephemeral URLSession (no persistent cache)**
- Using a **cache-busting query string** (`manifest.json?cacheBust=<timestamp>`) for each fetch
- Sending `Cache-Control: no-cache` / `Pragma: no-cache` request headers

## How to publish updates (checklist)

1. Put your “source” PDFs (named by identifier, e.g. `JFK.pdf`, `MCO.pdf`) into a folder.
2. Update `templates/manifest_template.json` (airport metadata). You typically do this once.
3. Run the generator:

```bash
python3 tools/generate_manifest.py \
  --source ./source-pdfs \
  --template ./templates/manifest_template.json \
  --site ./docs \
  --base-url "https://<username>.github.io/<repo>/"
```

Windows (PowerShell):

```powershell
py -3 tools\generate_manifest.py `
  --source .\source-pdfs `
  --template .\templates\manifest_template.json `
  --site .\docs `
  --base-url "https://<username>.github.io/<repo>/"
```

4. Commit the published outputs:
   - `docs/manifest.json`
   - `docs/manifests/manifest-*.json`
   - `docs/pdfs/**` (new hashed PDFs)
5. Push to GitHub. GitHub Pages will update automatically.

## Rollback (checklist)

To roll back, you only need to point `docs/manifest.json` back to an older archived manifest:

1. Choose a previous manifest in `docs/manifests/`.
2. Copy it over the stable manifest:

```bash
cp docs/manifests/manifest-2026-01-31T200000Z.json docs/manifest.json
```

3. Commit + push.

Since PDFs are immutable and stored by SHA, the old manifest will still reference valid PDFs.

## Optional GitHub Action

An optional workflow is provided in `.github/workflows/generate-manifest.yml`.

It can regenerate the manifest on every push, **but only works if the “source PDFs” are committed inside this repo** (for example in `source-pdfs/`). If you keep PDFs outside the repo, run the generator locally instead.


## Verify the published URLs

After enabling GitHub Pages, verify these URLs in a browser:

- `https://<username>.github.io/<repo>/manifest.json`
- A PDF from the manifest, e.g. `https://<username>.github.io/<repo>/pdfs/JFK/<sha256>.pdf`

If you get a `404`, see **Troubleshooting** below.

## Troubleshooting

### 404 when loading `manifest.json`

- Confirm GitHub Pages is enabled (Repo → Settings → Pages).
- Confirm the **Build and deployment** source is `Deploy from a branch`.
- Confirm **Branch** is `main` and **Folder** is `/docs`.
- Confirm the file exists at `docs/manifest.json` on the `main` branch.

### I updated the manifest but ABGViewer still shows the old version

- This is almost always client/proxy caching.
- ABGViewer adds cache-busting, but you can sanity-check by opening:
  - `https://<username>.github.io/<repo>/manifest.json?cacheBust=123`

### SHA mismatch in ABGViewer

- Ensure the PDF hosted at the URL in `manifest.json` matches the SHA recorded.

macOS/Linux:

```bash
shasum -a 256 /path/to/JFK.pdf
```

Linux (alt):

```bash
sha256sum /path/to/JFK.pdf
```

Windows (PowerShell):

```powershell
Get-FileHash -Algorithm SHA256 .\JFK.pdf
```

If hashes differ, re-run the generator and re-upload the correct PDF.

