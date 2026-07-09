#!/usr/bin/env python3
"""Scrape ONE category at a time to avoid timeouts. Usage: python scrape_one.py <slug> <pages>"""
import sys
import json
import os
import re
import time
import urllib.request
from html import unescape
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = "https://9jarocks.net"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}
OUTPUT = "/home/z/my-project/scripts/movies_dataset.json"

CATS = {
    "nollywood": ("Nollywood", "nollywood-movie"),
    "nollywood-series": ("Nollywood Series", "nollywood-tv-series"),
    "hollywood": ("Hollywood", "hollywood-movie"),
    "hollywood-series": ("Hollywood Series", "hollywood-tv-series"),
    "foreign": ("Foreign Movies", "foreign-movies"),
    "other-foreign-series": ("Other Foreign Series", "other-foreign-series"),
    "korean-drama": ("Korean Drama", "korean-drama"),
    "chinese-drama": ("Chinese Drama", "chinese-drama"),
    "thai-drama": ("Thai Drama", "thai-drama"),
    "filipino-drama": ("Filipino Drama", "filipino-drama"),
    "japanese-drama": ("Japanese Drama", "japanese-drama"),
    "anime": ("Anime", "anime"),
    "wrestling": ("Pro Wrestling", "pro-wrestling-fighting-sports"),
    "ongoing": ("Ongoing Series", "ongoing"),
}

def fetch(url, timeout=20):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except:
            if attempt < 2: time.sleep(2)
            else: raise

def strip_tags(s):
    if not s: return ""
    s = re.sub(r'<[^>]+>', ' ', s)
    return re.sub(r'\s+', ' ', unescape(s)).strip()

def get_urls(cat_url, cat_slug, max_pages):
    movies = []
    seen = set()
    for page in range(1, max_pages + 1):
        url = cat_url if page == 1 else f"{cat_url}/page/{page}"
        try:
            html = fetch(url)
        except: break
        page_movies = []
        for m in re.finditer(r'<a[^>]+href="(https?://9jarocks\.net/videodownload/[^"]+-id\d+\.html)"[^>]*>(.*?)</a>', html, re.S):
            link = m.group(1)
            if '#comment-' in link: continue
            text = strip_tags(m.group(2))
            if not text or len(text) < 4 or text.lower().startswith('download'): continue
            if link in seen: continue
            seen.add(link)
            page_movies.append({"url": link, "title": text[:200], "poster": None})
        # Posters
        for art in re.findall(r'<article[^>]*>(.*?)</article>', html, re.S):
            lm = re.search(r'<a[^>]+href="(https?://9jarocks\.net/videodownload/[^"]+-id\d+\.html)"', art)
            if not lm: continue
            im = re.search(r'<img[^>]+src="(https?://9jarocks\.net/wp-content/uploads/[^"]+)"', art)
            if im:
                for pm in page_movies:
                    if pm["url"] == lm.group(1) and not pm["poster"]:
                        pm["poster"] = im.group(1)
        preferred = [pm for pm in page_movies if cat_slug in pm["url"].lower()]
        others = [pm for pm in page_movies if pm not in preferred]
        movies.extend(preferred + others)
        print(f"  page {page}: {len(page_movies)} movies")
        if not page_movies or f'/page/{page+1}' not in html: break
        time.sleep(0.3)
    return movies

def parse_detail(url, fallback_title=None, fallback_poster=None, category=None, category_slug=None):
    html = fetch(url)
    data = {"url": url, "category": category, "category_slug": category_slug}
    m = re.search(r'<meta property="og:title"\s+content="([^"]+)"', html) or re.search(r'<title>([^<]+)</title>', html)
    title = strip_tags(m.group(1)).replace(" - 9jarocks", "").replace(" Mp4 Mkv Download", "").strip() if m else (fallback_title or "")
    data["title"] = title or fallback_title
    m = re.search(r'<meta property="og:image"\s+content="([^"]+)"', html)
    poster = m.group(1) if m else None
    if not poster:
        for img in re.findall(r'<img[^>]+src="(https?://9jarocks\.net/wp-content/uploads/[^"]+)"', html):
            if "Download-Button" not in img and "thumb" not in img.lower(): poster = img; break
    data["poster"] = poster or fallback_poster
    yt = re.search(r'<iframe[^>]*src="(https://www\.youtube\.com/embed/[^"]+)"', html)
    data["trailer_url"] = yt.group(1).split("?")[0] if yt else ""
    plot = ""
    for p in re.findall(r'<p[^>]*>(.*?)</p>', html, re.S):
        txt = strip_tags(p)
        if len(txt) > 80 and not txt.lower().startswith("filename") and "filesize" not in txt.lower(): plot = txt; break
    data["plot"] = plot[:1500]
    meta = {}
    for field, pat in [("year", r'Year:\s*(\d{4})'), ("type", r'Type:\s*([A-Za-z\s]+?)(?:<|\n|Country:)'),
                       ("country", r'Country:\s*([A-Za-z\s,]+?)(?:<|\n|Language:)'), ("language", r'Language:\s*([A-Za-z\s,]+?)(?:<|\n|Genre:)'),
                       ("genre", r'Genre:\s*([A-Za-z,/&\s]+?)(?:<|\n|Stars:)'), ("duration", r'Duration:\s*(\d+\s*min)'),
                       ("status", r'Status:\s*([A-Za-z\s]+?)(?:<|\n)')]:
        mm = re.search(pat, html)
        if mm: meta[field] = strip_tags(mm.group(1)).strip(' ,&')
    mm = re.search(r'Imdb:\s*-?\s*(https?://[^\s<]+)', html)
    if mm: meta["imdb_url"] = mm.group(1)
    data["meta"] = meta
    downloads = []
    for m in re.finditer(r'<a[^>]*class="[^"]*fa-fa-download[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        href, text = m.group(1), strip_tags(m.group(2))
        if "obqj2.com" in href or "associationfoam.com" in href: continue
        label = text or "Download"
        q = re.search(r'\.(\d{3,4}p)\.', href, re.I)
        ep = re.search(r'S\d+E\d+', href, re.I)
        if ep: label = ep.group(0)
        elif q: label = f"Download {q.group(1)}"
        downloads.append({"label": label, "url": href, "quality": q.group(1) if q else "", "size": ""})
    data["downloads"] = downloads[:30]
    thumbs = list(dict.fromkeys(re.findall(r'(https?://9jarocks\.net/wp-content/uploads/[^"\s]+_thumb\.jpg)', html)))
    data["thumbnails"] = thumbs[:12]
    related = []
    rel = re.search(r'Related Articles(.*?)(?:Read Next|Comments|Leave a Reply|<footer)', html, re.S)
    if rel:
        for a in re.finditer(r'<a[^>]+href="(https?://9jarocks\.net/videodownload/[^"]+)"[^>]*>(.*?)</a>', rel.group(1), re.S):
            t = strip_tags(a.group(2))
            if t and len(t) > 3 and a.group(1) != url: related.append({"url": a.group(1), "title": t[:200]})
    data["related"] = related[:6]
    return data

# Main
slug = sys.argv[1] if len(sys.argv) > 1 else "hollywood"
pages = int(sys.argv[2]) if len(sys.argv) > 2 else 10
name, url_slug = CATS.get(slug, ("Unknown", slug))
cat_url = f"{BASE}/category/videodownload/{url_slug}"
print(f"=== Scraping {name} ({slug}) — {pages} pages ===")

# Load dataset
with open(OUTPUT, encoding="utf-8") as f:
    dataset = json.load(f)
existing_urls = {m["url"] for m in dataset["movies"]}
print(f"Dataset has {len(dataset['movies'])} movies, {sum(1 for m in dataset['movies'] if m.get('category_slug')==slug)} in {slug}")

# Step 1: Collect URLs
print("\nCollecting URLs...")
cat_movies = get_urls(cat_url, slug, pages)
new_movies = [m for m in cat_movies if m["url"] not in existing_urls]
print(f"Found {len(cat_movies)} movies ({len(new_movies)} new)")

# Save URLs immediately
for m in new_movies:
    dataset["movies"].append({"url": m["url"], "title": m["title"], "poster": m.get("poster"),
                              "category": name, "category_slug": slug, "plot": "", "meta": {},
                              "downloads": [], "thumbnails": [], "related": [], "trailer_url": ""})
with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump(dataset, f, indent=2, ensure_ascii=False)
print(f"Saved {len(new_movies)} new URLs. Dataset now: {len(dataset['movies'])} movies")

# Step 2: Fetch details for new movies
if new_movies:
    print(f"\nFetching details for {len(new_movies)} new movies...")
    results = []
    done = [0]
    def worker(t):
        try: return parse_detail(t["url"], t["title"], t.get("poster"), name, slug)
        except Exception as e:
            return {"url": t["url"], "title": t["title"], "poster": t.get("poster"), "category": name,
                    "category_slug": slug, "plot": "", "meta": {}, "downloads": [], "thumbnails": [],
                    "related": [], "trailer_url": ""}

    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(worker, t) for t in new_movies]
        for fut in as_completed(futs):
            d = fut.result()
            results.append(d)
            done[0] += 1
            if done[0] % 10 == 0:
                print(f"  [{done[0]}/{len(new_movies)}] {d.get('title','?')[:50]}")

    # Update dataset with full details
    url_to_result = {r["url"]: r for r in results}
    for m in dataset["movies"]:
        if m["url"] in url_to_result and not m.get("plot"):
            m.update(url_to_result[m["url"]])
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(dataset, f, indent=2, ensure_ascii=False)

print(f"\n=== DONE ===")
print(f"Dataset: {len(dataset['movies'])} movies")
cat_count = sum(1 for m in dataset['movies'] if m.get('category_slug') == slug)
print(f"{name}: {cat_count} movies")
