#!/usr/bin/env python3
"""
Comprehensive paginated scraper for 9jarocks.net.
Fetches multiple pages per category to capture more movies.
Saves incrementally so progress is preserved if interrupted.
"""
import json
import os
import re
import time
import threading
import urllib.request
from urllib.parse import urljoin
from html import unescape
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = "https://9jarocks.net"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": BASE,
}
OUTPUT = "/home/z/my-project/scripts/movies_dataset.json"
LOCK = threading.Lock()

PAGES_PER_CATEGORY = int(os.environ.get("PAGES", "5"))

CATEGORIES = [
    {"name": "Korean Drama", "slug": "korean-drama", "url": f"{BASE}/category/videodownload/korean-drama"},
    {"name": "Chinese Drama", "slug": "chinese-drama", "url": f"{BASE}/category/videodownload/chinese-drama"},
    {"name": "Thai Drama", "slug": "thai-drama", "url": f"{BASE}/category/videodownload/thai-drama"},
    {"name": "Filipino Drama", "slug": "filipino-drama", "url": f"{BASE}/category/videodownload/filipino-drama"},
    {"name": "Japanese Drama", "slug": "japanese-drama", "url": f"{BASE}/category/videodownload/japanese-drama"},
    {"name": "Anime", "slug": "anime", "url": f"{BASE}/category/videodownload/anime"},
    {"name": "Pro Wrestling", "slug": "wrestling", "url": f"{BASE}/category/videodownload/pro-wrestling-fighting-sports"},
    {"name": "Other Foreign Series", "slug": "other-foreign-series", "url": f"{BASE}/category/videodownload/other-foreign-series"},
    {"name": "Foreign Movies", "slug": "foreign", "url": f"{BASE}/category/videodownload/foreign-movies"},
    {"name": "Ongoing Series", "slug": "ongoing", "url": f"{BASE}/category/videodownload/ongoing"},
    {"name": "Nollywood", "slug": "nollywood", "url": f"{BASE}/category/videodownload/nollywood-movie"},
    {"name": "Nollywood Series", "slug": "nollywood-series", "url": f"{BASE}/category/videodownload/nollywood-tv-series"},
    {"name": "Hollywood", "slug": "hollywood", "url": f"{BASE}/category/videodownload/hollywood-movie"},
    {"name": "Hollywood Series", "slug": "hollywood-series", "url": f"{BASE}/category/videodownload/hollywood-tv-series"},
]


def fetch(url, timeout=20):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
            else:
                raise


def strip_tags(s):
    if not s: return ""
    s = re.sub(r'<script[^>]*>.*?</script>', '', s, flags=re.S | re.I)
    s = re.sub(r'<style[^>]*>.*?</style>', '', s, flags=re.S | re.I)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = unescape(s)
    return re.sub(r'\s+', ' ', s).strip()


def get_category_movies_paged(cat_url, cat_slug, max_pages=5):
    all_movies = []
    seen_urls = set()
    for page_num in range(1, max_pages + 1):
        url = cat_url if page_num == 1 else f"{cat_url}/page/{page_num}"
        try:
            html = fetch(url)
        except Exception as e:
            print(f"    page {page_num}: ERROR {e}")
            break

        page_movies = []
        for m in re.finditer(r'<a[^>]+href="(https?://9jarocks\.net/videodownload/[^"]+-id\d+\.html)"[^>]*>(.*?)</a>', html, re.S):
            link_url = m.group(1)
            if '#comment-' in link_url:
                continue
            text = strip_tags(m.group(2))
            if not text or len(text) < 4:
                continue
            if text.lower().startswith('download'):
                continue
            if link_url in seen_urls:
                continue
            seen_urls.add(link_url)
            page_movies.append({"url": link_url, "title": text[:200], "poster": None})

        # Posters from article blocks
        poster_map = {}
        for art in re.findall(r'<article[^>]*>(.*?)</article>', html, re.S):
            link_m = re.search(r'<a[^>]+href="(https?://9jarocks\.net/videodownload/[^"]+-id\d+\.html)"', art)
            if not link_m:
                continue
            u = link_m.group(1)
            if u in poster_map:
                continue
            img_m = re.search(r'<img[^>]+src="(https?://9jarocks\.net/wp-content/uploads/[^"]+)"', art)
            if not img_m:
                img_m = re.search(r'<img[^>]+data-src="(https?://9jarocks\.net/wp-content/uploads/[^"]+)"', art)
            if img_m:
                poster_map[u] = img_m.group(1)

        for pm in page_movies:
            pm["poster"] = poster_map.get(pm["url"])

        preferred = [pm for pm in page_movies if cat_slug in pm["url"].lower() or cat_slug.replace('-', ' ') in pm["title"].lower()]
        others = [pm for pm in page_movies if pm not in preferred]
        ordered = preferred + others

        all_movies.extend(ordered)
        print(f"    page {page_num}: {len(page_movies)} movies")

        if not page_movies:
            break
        if f'/page/{page_num + 1}' not in html:
            break
        time.sleep(0.3)

    return all_movies


def parse_movie_detail(url, fallback_title=None, fallback_poster=None, category=None, category_slug=None):
    html = fetch(url)
    data = {"url": url, "category": category, "category_slug": category_slug}

    m = re.search(r'<meta property="og:title"\s+content="([^"]+)"', html)
    if not m:
        m = re.search(r'<title>([^<]+)</title>', html)
    title = strip_tags(m.group(1)) if m else (fallback_title or "")
    title = title.replace(" - 9jarocks", "").replace(" Mp4 Mkv Download", "").strip()
    data["title"] = title or fallback_title

    m = re.search(r'<meta property="og:image"\s+content="([^"]+)"', html)
    poster = m.group(1) if m else None
    if not poster:
        for img in re.findall(r'<img[^>]+src="(https?://9jarocks\.net/wp-content/uploads/[^"]+)"', html):
            if "Download-Button" not in img and "thumb" not in img.lower():
                poster = img
                break
    data["poster"] = poster or fallback_poster

    trailer_url = ""
    yt_m = re.search(r'<iframe[^>]*src="(https://www\.youtube\.com/embed/[^"]+)"', html)
    if not yt_m:
        yt_m = re.search(r'<iframe[^>]*src="(https://youtube\.com/embed/[^"]+)"', html)
    if yt_m:
        trailer_url = yt_m.group(1).split("?")[0]
    data["trailer_url"] = trailer_url

    plot = ""
    for p in re.findall(r'<p[^>]*>(.*?)</p>', html, re.S):
        txt = strip_tags(p)
        if len(txt) > 80 and not txt.lower().startswith("filename") and "filesize" not in txt.lower():
            plot = txt
            break
    data["plot"] = plot[:1500]

    meta = {}
    for field, pat in [
        ("year", r'Year:\s*(\d{4})'),
        ("type", r'Type:\s*([A-Za-z\s]+?)(?:<|\n|Country:)'),
        ("country", r'Country:\s*([A-Za-z\s,]+?)(?:<|\n|Language:)'),
        ("language", r'Language:\s*([A-Za-z\s,]+?)(?:<|\n|Genre:)'),
        ("genre", r'Genre:\s*([A-Za-z,/&\s]+?)(?:<|\n|Stars:)'),
        ("duration", r'Duration:\s*(\d+\s*min)'),
        ("total_episodes", r'Total Episodes:\s*(\d+)'),
        ("status", r'Status:\s*([A-Za-z\s]+?)(?:<|\n)'),
    ]:
        mm = re.search(pat, html)
        if mm:
            meta[field] = strip_tags(mm.group(1)).strip(' ,&')
    mm = re.search(r'Imdb:\s*-?\s*(https?://[^\s<]+)', html)
    if mm:
        meta["imdb_url"] = mm.group(1)
    data["meta"] = meta

    downloads = []
    for m in re.finditer(r'<a[^>]*class="[^"]*fa-fa-download[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        href = m.group(1)
        text = strip_tags(m.group(2))
        if "obqj2.com" in href or "associationfoam.com" in href:
            continue
        label = text or "Download"
        quality = ""
        q_m = re.search(r'\.(\d{3,4}p)\.', href, re.I)
        if q_m:
            quality = q_m.group(1)
        ep_m = re.search(r'S\d+E\d+', href, re.I) or re.search(r'Episode\.?\s*\d+', href, re.I)
        if ep_m:
            label = ep_m.group(0)
        elif quality:
            label = f"Download {quality}"
        else:
            fn_m = re.search(r'/([^/]+\.(?:mkv|mp4|avi))', href)
            if fn_m:
                fn = fn_m.group(1).replace("%5B", "[").replace("%5D", "]").replace(".", " ")
                label = fn[:60]
        size = ""
        url_filename = href.split("/")[-1].replace("%5B", "[").replace("%5D", "]")
        size_m = re.search(r'Filename:\s*' + re.escape(url_filename[:30]) + r'[^<]*?Filesize:\s*([\d.]+\s*(?:MB|GB))', html)
        if size_m:
            size = size_m.group(1)
        downloads.append({"label": label, "url": href, "quality": quality, "size": size})
    data["downloads"] = downloads[:30]

    thumbs = []
    for img in re.findall(r'(https?://9jarocks\.net/wp-content/uploads/[^"\s]+_thumb\.jpg)', html):
        if img not in thumbs:
            thumbs.append(img)
    data["thumbnails"] = thumbs[:12]

    related = []
    rel_m = re.search(r'Related Articles(.*?)(?:Read Next|Comments|Leave a Reply|<footer)', html, re.S)
    if rel_m:
        for a in re.finditer(r'<a[^>]+href="(https?://9jarocks\.net/videodownload/[^"]+)"[^>]*>(.*?)</a>', rel_m.group(1), re.S):
            url_r, title_r = a.group(1), strip_tags(a.group(2))
            if title_r and len(title_r) > 3 and url_r != url:
                related.append({"url": url_r, "title": title_r[:200]})
    data["related"] = related[:6]
    return data


def load_existing():
    if Path(OUTPUT).exists():
        try:
            with open(OUTPUT, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"scraped_at": int(time.time()), "source": BASE,
            "categories": [{"name": c["name"], "slug": c["slug"]} for c in CATEGORIES],
            "movies": []}


def save_dataset(data):
    tmp = OUTPUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.rename(tmp, OUTPUT)


print(f"=== Scraper ===")
print(f"Pages per category: {PAGES_PER_CATEGORY}")
print()

dataset = load_existing()
existing_urls = {m["url"] for m in dataset["movies"]}
print(f"Resuming: {len(dataset['movies'])} movies already in dataset")

print("\n=== Step 1: Collecting movie URLs ===")
all_targets = []
seen_urls = set(existing_urls)
for c in CATEGORIES:
    print(f"\n  {c['name']}:")
    try:
        cat_movies = get_category_movies_paged(c["url"], c["slug"], PAGES_PER_CATEGORY)
        new_count = 0
        for m in cat_movies:
            if m["url"] not in seen_urls:
                seen_urls.add(m["url"])
                all_targets.append({**m, "category": c["name"], "category_slug": c["slug"]})
                new_count += 1
        print(f"    -> {new_count} new movies")

        # Save URLs to dataset immediately after each category
        # (so progress is preserved even if scraper dies)
        with LOCK:
            # Add minimal entries (url, title, category) to dataset
            for m in cat_movies:
                if m["url"] not in {e["url"] for e in dataset["movies"]}:
                    dataset["movies"].append({
                        "url": m["url"],
                        "title": m["title"],
                        "poster": m.get("poster"),
                        "category": c["name"],
                        "category_slug": c["slug"],
                        "plot": "", "meta": {}, "downloads": [],
                        "thumbnails": [], "related": [], "trailer_url": "",
                    })
            save_dataset(dataset)
            existing_urls = {m["url"] for m in dataset["movies"]}
    except Exception as e:
        print(f"    ERROR: {e}")

print(f"\n=== Total new movies to fetch details for: {len(all_targets)} ===")

if not all_targets:
    print("No new movies to fetch. Exiting.")
    save_dataset(dataset)
    exit(0)

print(f"\n=== Step 2: Fetching details ({len(all_targets)} movies) ===")
results = list(dataset["movies"])
done_count = [0]
total = len(all_targets)

def worker(t):
    try:
        return parse_movie_detail(t["url"], t["title"], t.get("poster"), t["category"], t["category_slug"])
    except Exception as e:
        return {"url": t["url"], "title": t["title"], "poster": t.get("poster"),
                "category": t["category"], "category_slug": t["category_slug"],
                "plot": "", "meta": {}, "downloads": [], "thumbnails": [], "related": [],
                "trailer_url": "", "error": str(e)}

SAVE_EVERY = 25

with ThreadPoolExecutor(max_workers=6) as ex:
    futs = [ex.submit(worker, t) for t in all_targets]
    for fut in as_completed(futs):
        d = fut.result()
        with LOCK:
            results.append(d)
            done_count[0] += 1
            if done_count[0] % SAVE_EVERY == 0:
                dataset["movies"] = results
                save_dataset(dataset)
            if done_count[0] % 10 == 0:
                print(f"  [{done_count[0]}/{total}] {d.get('title','?')[:50]} | DLs:{len(d.get('downloads',[]))} | Tr:{'Y' if d.get('trailer_url') else 'N'}")

dataset["movies"] = results
save_dataset(dataset)

with_poster = sum(1 for m in results if m.get("poster"))
with_plot = sum(1 for m in results if m.get("plot"))
with_downloads = sum(1 for m in results if m.get("downloads"))
with_trailer = sum(1 for m in results if m.get("trailer_url"))
total_dls = sum(len(m.get("downloads", [])) for m in results)

print(f"\n=== DONE ===")
print(f"Total movies: {len(results)}")
print(f"With poster: {with_poster}")
print(f"With plot: {with_plot}")
print(f"With downloads: {with_downloads} (total {total_dls} links)")
print(f"With trailer: {with_trailer}")

from collections import Counter
cats = Counter(m.get("category_slug", "?") for m in results)
print("\nMovies per category:")
for slug, n in sorted(cats.items()):
    print(f"  {slug}: {n}")
