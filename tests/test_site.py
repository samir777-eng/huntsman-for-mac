# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Huntsman for Mac contributors
"""Checks on the GitHub Pages landing page in docs/: assets, SEO metadata, structured data and truthfulness."""
import html.parser
import json
import pathlib
import re
import urllib.parse
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SITE = "https://samir777-eng.github.io/huntsman-for-mac/"
REPO = "https://github.com/samir777-eng/huntsman-for-mac"


class _Page(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []          # (tag, attrs dict)
        self.scripts = []       # (attrs dict, text)
        self._script = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append((tag, a))
        if tag == "script":
            self._script = (a, [])

    def handle_data(self, data):
        if self._script is not None:
            self._script[1].append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._script is not None:
            self.scripts.append((self._script[0], "".join(self._script[1])))
            self._script = None


def _html():
    return (DOCS / "index.html").read_text(encoding="utf-8")


def _page():
    p = _Page()
    p.feed(_html())
    return p


def _version():
    m = re.search(r'^__version__ = "([^"]+)"', (ROOT / "huntsman_core.py").read_text(encoding="utf-8"), re.M)
    return m.group(1)


def _json_ld():
    return [json.loads(text) for a, text in _page().scripts if a.get("type") == "application/ld+json"]


def _of_type(kind):
    found = [d for d in _json_ld() if d.get("@type") == kind]
    assert len(found) == 1, f"expected one {kind} JSON-LD block"
    return found[0]


def _meta(page, key, value):
    return [a.get("content") for t, a in page.tags if t == "meta" and a.get(key) == value]


def test_index_has_the_licence_header():
    assert "SPDX-License-Identifier: GPL-3.0-or-later" in _html()[:400]


def test_every_local_asset_exists():
    refs = []
    for tag, a in _page().tags:
        for attr in ("src", "href", "poster"):
            if a.get(attr):
                refs.append(a[attr])
        if a.get("srcset"):
            refs += [part.strip().split()[0] for part in a["srcset"].split(",")]
    local = [r for r in refs if not urllib.parse.urlparse(r).scheme and not r.startswith(("#", "//", "mailto:"))]
    assert local, "the page should use the images in docs/"
    missing = [r for r in local if not (DOCS / urllib.parse.unquote(r.split("#")[0].split("?")[0])).is_file()]
    assert missing == []


def test_images_have_alt_text_and_size():
    imgs = [a for t, a in _page().tags if t == "img"]
    assert len(imgs) >= 5
    assert all(a.get("alt", "").strip() for a in imgs)
    assert all(a.get("width") and a.get("height") for a in imgs), "width/height avoid layout shift"


def test_no_external_scripts_and_no_trackers():
    page = _page()
    assert [a for a, _ in page.scripts if a.get("src")] == []
    low = _html().lower()
    for word in ("google-analytics", "googletagmanager", "gtag(", "plausible", "doubleclick", "document.cookie"):
        assert word not in low


def test_canonical_and_social_urls_are_absolute_on_the_pages_domain():
    page = _page()
    canon = [a["href"] for t, a in page.tags if t == "link" and a.get("rel") == "canonical"]
    assert canon == [SITE]
    assert _meta(page, "property", "og:url") == [SITE]
    assert _meta(page, "property", "og:image") == [SITE + "social-preview.png"]
    assert _meta(page, "name", "twitter:image") == [SITE + "social-preview.png"]
    assert _meta(page, "name", "twitter:card") == ["summary_large_image"]
    desc = _meta(page, "name", "description")
    assert len(desc) == 1 and 50 <= len(desc[0]) <= 170
    assert (DOCS / "social-preview.png").is_file()


def test_title_names_the_keyboard_and_mac():
    title = re.search(r"<title>([^<]+)</title>", _html()).group(1)
    assert "Huntsman V3 Pro" in title and ("Mac" in title or "macOS" in title)


def test_software_application_json_ld_matches_the_code():
    app = _of_type("SoftwareApplication")
    assert app["softwareVersion"] == _version()
    assert f"v{_version()}" in _html(), "the visible version badge should match too"
    assert app["operatingSystem"] == "macOS"
    assert app["name"] == "Huntsman for Mac"
    assert app["offers"]["price"] in ("0", 0)
    assert "GPL-3.0" in app["license"]
    assert app["url"] == SITE
    assert REPO in (app.get("codeRepository"), app.get("downloadUrl"), *app.get("sameAs", []))


def test_faq_json_ld_parses_and_uses_the_readme_questions():
    faq = _of_type("FAQPage")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    qs = faq["mainEntity"]
    assert len(qs) >= 5
    for q in qs:
        assert q["@type"] == "Question" and q["acceptedAnswer"]["@type"] == "Answer"
        assert q["name"] in readme, q["name"]
        assert q["acceptedAnswer"]["text"].strip()
    # the visible FAQ shows the same questions
    shown = [a for t, a in _page().tags if t == "details"]
    assert len(shown) >= len(qs)
    for q in qs:
        assert q["name"] in _html()


def test_page_is_truthful_about_testing_and_media():
    text = _html()
    assert "02A6" in text
    assert "xperimental" in text and "untested" in text
    assert "demo mode" in text
    assert "at the time of writing" in text
    assert "Unofficial" in text and "trademarks of Razer Inc." in text
    assert "GPL-3.0-or-later" in text
    assert "OpenRazer" in text and "easyrazer" in text
    for model in ("V3 Pro TKL", "V3 Pro 8KHz", "V3 Pro Mini", "V2 TKL", "V2 Analog"):
        assert model in text


def test_page_basics_for_accessibility_and_layout():
    text = _html()
    assert re.search(r'<html lang="en"', text)
    assert '<meta name="viewport"' in text
    for landmark in ("<header", "<main", "<footer", "<nav"):
        assert landmark in text
    assert "prefers-reduced-motion" in text
    assert "git clone https://github.com/samir777-eng/huntsman-for-mac.git" in text
    assert "./install.sh" in text


def test_robots_and_sitemap_point_at_the_site():
    robots = (DOCS / "robots.txt").read_text(encoding="utf-8")
    assert "User-agent: *" in robots and f"Sitemap: {SITE}sitemap.xml" in robots
    tree = ET.parse(DOCS / "sitemap.xml")
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    assert [e.text for e in tree.getroot().findall("s:url/s:loc", ns)] == [SITE]


def test_nojekyll_is_present():
    assert (DOCS / ".nojekyll").is_file()


def test_page_says_the_windows_build_is_experimental_and_untested():
    text = _html()
    win = text[text.index('id="windows"'):]
    win = win[:win.index("</section>")]
    assert "experimental" in win.lower() and "Untested" in win
    assert "never run on a Windows PC" in win
    assert "Huntsman-for-Windows-&lt;version&gt;.zip" in win
    assert "SmartScreen" in win and "Synapse" in win and "Dynamic Lighting" in win
    assert 'href="#windows"' in text
    assert "Does it work on Windows?" in text
