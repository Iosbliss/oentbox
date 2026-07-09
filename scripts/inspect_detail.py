#!/usr/bin/env python3
"""Fetch a real movie page and extract structured data (poster, year, genre, plot, downloads)."""
import json
import re
import urllib.request
from html.parser import HTMLParser

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
}

def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")

# Fetch a real movie detail page
url = "https://9jarocks.net/videodownload/the-chi-season-8-id391791.html"
html = fetch(url)
with open("/home/z/my-project/scripts/sample_movie.html", "w", encoding="utf-8") as f:
    f.write(html)
print(f"Saved {len(html)} bytes from {url}")

# Try to find og:image, title, description
og_image = re.search(r'<meta property="og:image"\s+content="([^"]+)"', html)
title = re.search(r'<title>([^<]+)</title>', html)
desc = re.search(r'<meta name="description"\s+content="([^"]+)"', html)
print(f"\nTitle: {title.group(1) if title else 'N/A'}")
print(f"OG Image: {og_image.group(1) if og_image else 'N/A'}")
print(f"Description: {desc.group(1)[:200] if desc else 'N/A'}")

# Find all images with their src and any alt
imgs = re.findall(r'<img[^>]+>', html)
print(f"\nFound {len(imgs)} <img> tags. First 10:")
for i, t in enumerate(imgs[:10]):
    src = re.search(r'src="([^"]+)"', t)
    alt = re.search(r'alt="([^"]+)"', t)
    print(f"  {i}: src={src.group(1) if src else 'N/A'}")
    print(f"     alt={alt.group(1) if alt else 'N/A'}")

# Try to find download links (anchors with "download" in href or text)
print("\n\nDownload-related links:")
dl_links = re.findall(r'<a[^>]*href="([^"]*(?:download|mp4|mkv|avi|720|1080)[^"]*)"[^>]*>([^<]*)</a>', html, re.I)
for h, t in dl_links[:20]:
    print(f"  {t.strip()[:60]} -> {h[:80]}")

# Find headings inside content (h1/h2/h3)
print("\n\nHeadings (h1-h3):")
for h in re.findall(r'<h[123][^>]*>(.*?)</h[123]>', html, re.S):
    txt = re.sub(r'<[^>]+>', '', h).strip()
    if txt:
        print(f"  - {txt[:120]}")

# Find paragraphs with plot-like text
print("\n\nFirst 5 paragraphs of body content:")
for p in re.findall(r'<p[^>]*>(.*?)</p>', html, re.S)[:5]:
    txt = re.sub(r'<[^>]+>', '', p).strip()
    if len(txt) > 30:
        print(f"  > {txt[:300]}")
        print()

# Look for tags / genres (often in <a href="/tag/...">)
print("\n\nTag links:")
tags = re.findall(r'<a[^>]*href="[^"]*\/tag\/([^"\/]+)"[^>]*>([^<]+)</a>', html)
for slug, name in tags[:20]:
    print(f"  - {name.strip()} ({slug})")

# Now scrape a category page to find more movies with posters
print("\n\n=== Scraping Nollywood category ===")
cat_url = "https://9jarocks.net/category/videodownload/nollywood-movie"
cat_html = fetch(cat_url)
print(f"Category page size: {len(cat_html)}")

# Look for article/post blocks
articles = re.findall(r'<article[^>]*>(.*?)</article>', cat_html, re.S)
print(f"Found {len(articles)} <article> blocks")

# Try common WordPress patterns - look for h2 > a inside article-like divs
# Pattern: <h2 class="..."><a href="...">Title</a></h2>
posts = re.findall(r'<h[12][^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', cat_html)
print(f"\nFound {len(posts)} post title links. First 15:")
for u, t in posts[:15]:
    print(f"  - {t.strip()[:70]} -> {u[:80]}")

# Find images in the category page that look like posters (often have alt=title)
print("\nFirst 15 images in category page:")
for t in re.findall(r'<img[^>]+>', cat_html)[:15]:
    src = re.search(r'(?:src|data-src)="([^"]+)"', t)
    alt = re.search(r'alt="([^"]+)"', t)
    if src and ('9jarocks' in src.group(1) or 'wp-content' in src.group(1)):
        print(f"  src: {src.group(1)[:120]}")
        print(f"  alt: {alt.group(1)[:80] if alt else 'N/A'}")
        print()

with open("/home/z/my-project/scripts/category_raw.html", "w", encoding="utf-8") as f:
    f.write(cat_html)
print(f"\nSaved category HTML to scripts/category_raw.html")
