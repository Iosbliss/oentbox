#!/usr/bin/env python3
"""Scrape 9jarocks.net to understand its structure and gather sample movie data."""
import json
import re
import time
import urllib.request
from urllib.parse import urljoin, urlparse
from html.parser import HTMLParser

BASE = "https://9jarocks.net/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")

class LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.in_a = False
        self.current_href = None
        self.current_text = []
        self.current_img = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a":
            self.in_a = True
            self.current_href = attrs.get("href")
            self.current_text = []
            self.current_img = None
        elif tag == "img" and self.in_a:
            self.current_img = attrs.get("src") or attrs.get("data-src")

    def handle_data(self, data):
        if self.in_a:
            self.current_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.in_a:
            text = " ".join(" ".join(self.current_text).split())
            if self.current_href:
                self.links.append({
                    "href": self.current_href,
                    "text": text,
                    "img": self.current_img,
                })
            self.in_a = False
            self.current_href = None
            self.current_text = []
            self.current_img = None

class MetaCollector(HTMLParser):
    """Collect title, meta description, and og:image."""
    def __init__(self):
        super().__init__()
        self.title = None
        self.description = None
        self.og_image = None
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "title":
            self.in_title = True
        elif tag == "meta":
            name = attrs.get("name", "").lower()
            prop = attrs.get("property", "").lower()
            if name == "description":
                self.description = attrs.get("content")
            elif prop == "og:image":
                self.og_image = attrs.get("content")

    def handle_data(self, data):
        if self.in_title:
            self.title = (self.title or "") + data

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

def extract_movie_links(html, base):
    """Find links that look like movie pages (title, year, etc.)."""
    p = LinkCollector()
    p.feed(html)
    movie_links = []
    seen = set()
    for l in p.links:
        href = l["href"]
        if not href:
            continue
        full = urljoin(base, href)
        # Filter: must be on same domain, look like a movie/article URL
        if "9jarocks.net" not in full:
            continue
        # Skip category/tag/author/page links
        path = urlparse(full).path.lower()
        if any(s in path for s in ["/category/", "/tag/", "/author/", "/page/", "/wp-", "/feed"]):
            continue
        if path in ("", "/"):
            continue
        if full in seen:
            continue
        seen.add(full)
        text = l["text"].strip()
        if len(text) < 3:
            continue
        movie_links.append({
            "url": full,
            "title": text[:200],
            "img": l["img"],
        })
    return movie_links

def extract_categories(html, base):
    """Find category links in nav/menu."""
    p = LinkCollector()
    p.feed(html)
    cats = []
    seen = set()
    for l in p.links:
        href = l["href"] or ""
        if "/category/" in href:
            full = urljoin(base, href)
            if full in seen:
                continue
            seen.add(full)
            text = l["text"].strip()
            if text and len(text) < 60:
                cats.append({"name": text, "url": full})
    return cats

print("Fetching homepage...")
home_html = fetch(BASE)
print(f"Homepage size: {len(home_html)} bytes")

# Save raw homepage for offline inspection
with open("/home/z/my-project/scripts/home_raw.html", "w", encoding="utf-8") as f:
    f.write(home_html)

# Get categories
cats = extract_categories(home_html, BASE)
print(f"Found {len(cats)} categories:")
for c in cats[:30]:
    print(f"  - {c['name']} -> {c['url']}")

# Get movie links from homepage
movies = extract_movie_links(home_html, BASE)
print(f"\nFound {len(movies)} candidate movie links on homepage:")
for m in movies[:20]:
    print(f"  - {m['title'][:70]}")
    print(f"    URL: {m['url']}")
    print(f"    IMG: {m['img']}")

# Try to fetch a few detail pages to understand structure
print("\n\nFetching sample detail pages...")
detail_samples = []
for m in movies[:5]:
    try:
        print(f"  Fetching: {m['url']}")
        dhtml = fetch(m["url"])
        meta = MetaCollector()
        meta.feed(dhtml)
        detail_samples.append({
            "url": m["url"],
            "title": meta.title,
            "description": meta.description,
            "og_image": meta.og_image,
            "html_size": len(dhtml),
            "html_preview": dhtml[:2000],
        })
        time.sleep(1)
    except Exception as e:
        print(f"  Error: {e}")

# Save findings
out = {
    "base": BASE,
    "categories": cats,
    "homepage_movies": movies[:50],
    "detail_samples": detail_samples,
}
with open("/home/z/my-project/scripts/scrape_results.json", "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)

print(f"\n\nSaved scrape results to /home/z/my-project/scripts/scrape_results.json")
print(f"Categories: {len(cats)}")
print(f"Homepage movies found: {len(movies)}")
print(f"Detail samples fetched: {len(detail_samples)}")
