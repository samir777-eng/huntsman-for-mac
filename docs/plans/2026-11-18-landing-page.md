# GitHub Pages landing page (2026-11-18)

## Goal
A one-page site at https://samir777-eng.github.io/huntsman-for-mac/ so people searching "Razer Huntsman V3 Pro Mac",
"Huntsman V3 Pro actuation macOS", "Synapse Mac Huntsman" find the project, then go to GitHub.

## Requirements
- `docs/index.html`, self-contained (inline CSS, no external JS; Google Fonts optional), in the README's look (dark,
  ice #6ad7ff), using existing assets: docs/banner.png, demo GIFs, screenshots, social-preview.png.
- Content = README facts only: only the V3 Pro 02A6 tested; six models experimental/untested; Synapse for Mac doesn't
  support its settings (at the time of writing); demo-mode media labelled; unofficial/trademark note; GPL-3.0.
- SEO: title, meta description, canonical, Open Graph + Twitter card (social-preview.png, absolute URL), JSON-LD
  SoftwareApplication (name, OS macOS, free, version from huntsman_core.__version__, licence, repo URL),
  `robots.txt`, `sitemap.xml`; FAQ section with FAQPage JSON-LD using README FAQ answers.
- Accessible (landmarks, alt text, contrast AA, reduced motion), responsive to 320 px, no horizontal scroll.
- `.nojekyll` so files are served as-is. No analytics, no cookies, no trackers.
- Pages source: branch master, folder /docs.

## Tests (first)
tests/test_site.py: every local asset referenced by index.html exists; version in JSON-LD equals __version__;
canonical/OG URLs absolute on the Pages domain; FAQPage JSON-LD parses; no external <script src>; robots/sitemap
present and point at the site; SPDX header (tests/test_repo.py rules).
