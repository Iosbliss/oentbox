#!/usr/bin/env python3
"""Enhanced scraper — extracts real download URLs (loadedfiles.org) and YouTube trailers."""
import json
import re
import time
import threading
import urllib.request
from urllib.parse import urljoin
from html import unescape
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://9jarocks.net"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
}
CATEGORIES = [
    {"name": "Nollywood", "slug": "nollywood", "url": f"{BASE}/category/videodownload/nollywood-movie"},
    {"name": "Nollywood Series", "slug": "nollywood-series", "url": f"{BASE}/category/videodownload/nollywood-tv-series"},
    {"name": "Hollywood", "slug": "hollywood", "url": f"{BASE}/category/videodownload/hollywood-movie"},
    {"name": "Hollywood Series", "slug": "hollywood-series", "url": f"{BASE}/category/videodownload/hollywood-tv-series"},
    {"name": "Foreign Movies", "slug": "foreign", "url": f"{BASE}/category/videodownload/foreign-movies"},
    {"name": "Korean Drama", "slug": "korean-drama", "url": f"{BASE}/category/videodownload/korean-drama"},
    {"name": "Anime", "slug": "anime", "url": f"{BASE}/category/videodownload/anime"},
    {"name": "Pro Wrestling", "slug": "wrestling", "url": f"{BASE}/category/videodownload/pro-wrestling-fighting-sports"},
]
OUTPUT = "/home/z/my-project/scripts/movies_dataset.json"
lock = threading.Lock()


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def strip_tags(s):
    if not s: return ""
    s = re.sub(r'<script[^>]*>.*?</script>', '', s, flags=re.S|re.I)
    s = re.sub(r'<style[^>]*>.*?</style>', '', s, flags=re.S|re.I)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = unescape(s)
    return re.sub(r'\s+', ' ', s).strip()


def get_category_movies(cat_url, max_movies=8):
    html = fetch(cat_url)
    movies = []
    seen = set()
    articles = re.findall(r'<article[^>]*>(.*?)</article>', html, re.S)
    for art in articles:
        link_m = re.search(r'<a[^>]+href="(https?://9jarocks\.net/videodownload/[^"]+)"[^>]*>(.*?)</a>', art, re.S)
        if not link_m: continue
        url = link_m.group(1)
        if url in seen: continue
        title_m = re.search(r'<h[23][^>]*>(.*?)</h[23]>', art, re.S)
        title = strip_tags(title_m.group(1)) if title_m else strip_tags(link_m.group(2))
        img_m = re.search(r'<img[^>]+src="(https?://9jarocks\.net/wp-content/uploads/[^"]+)"', art)
        if not img_m:
            img_m = re.search(r'<img[^>]+data-src="(https?://9jarocks\.net/wp-content/uploads/[^"]+)"', art)
        poster = img_m.group(1) if img_m else None
        if title and len(title) > 3:
            seen.add(url)
            movies.append({"url": url, "title": title[:200], "poster": poster})
            if len(movies) >= max_movies: break
    if len(movies) < 4:
        for m in re.finditer(r'<a[^>]+href="(https?://9jarocks\.net/videodownload/[^"]+-id\d+\.html)"[^>]*>(.*?)</a>', html, re.S):
            url = m.group(1)
            if url in seen: continue
            title = strip_tags(m.group(2))
            if title and len(title) > 5 and not title.lower().startswith("download"):
                seen.add(url)
                movies.append({"url": url, "title": title[:200], "poster": None})
                if len(movies) >= max_movies: break
    return movies


def parse_movie_detail(url, fallback_title=None, fallback_poster=None, category=None, category_slug=None):
    html = fetch(url)
    data = {"url": url, "category": category, "category_slug": category_slug}

    # Title
    m = re.search(r'<meta property="og:title"\s+content="([^"]+)"', html)
    if not m:
        m = re.search(r'<title>([^<]+)</title>', html)
    title = strip_tags(m.group(1)) if m else (fallback_title or "")
    title = title.replace(" - 9jarocks", "").replace(" Mp4 Mkv Download", "").strip()
    data["title"] = title or fallback_title

    # Poster
    m = re.search(r'<meta property="og:image"\s+content="([^"]+)"', html)
    poster = m.group(1) if m else None
    if not poster:
        for img in re.findall(r'<img[^>]+src="(https?://9jarocks\.net/wp-content/uploads/[^"]+)"', html):
            if "Download-Button" not in img and "thumb" not in img.lower():
                poster = img; break
    data["poster"] = poster or fallback_poster

    # Trailer: YouTube embed iframe
    trailer_url = ""
    # Look for oembed-style youtube embed
    yt_m = re.search(r'<iframe[^>]*src="(https://www\.youtube\.com/embed/[^"]+)"', html)
    if not yt_m:
        yt_m = re.search(r'<iframe[^>]*src="(https://youtube\.com/embed/[^"]+)"', html)
    if not yt_m:
        yt_m = re.search(r'<iframe[^>]*src="(https://www\.youtube-nocookie\.com/embed/[^"]+)"', html)
    if yt_m:
        trailer_url = yt_m.group(1)
        # Strip query string to get just the embed URL
        trailer_url = trailer_url.split("?")[0]
    data["trailer_url"] = trailer_url

    # Plot
    plot = ""
    for p in re.findall(r'<p[^>]*>(.*?)</p>', html, re.S):
        txt = strip_tags(p)
        if len(txt) > 80 and not txt.lower().startswith("filename") and "filesize" not in txt.lower():
            plot = txt; break
    data["plot"] = plot[:1500]

    # Metadata
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
        if mm: meta[field] = strip_tags(mm.group(1)).strip(' ,&')
    mm = re.search(r'Imdb:\s*-?\s*(https?://[^\s<]+)', html)
    if mm: meta["imdb_url"] = mm.group(1)
    data["meta"] = meta

    # REAL download links — extract from <a class="fa-fa-download" href="...">
    downloads = []
    for m in re.finditer(r'<a[^>]*class="[^"]*fa-fa-download[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        href = m.group(1)
        text = strip_tags(m.group(2))
        # Filter to actual file host links (loadedfiles.org, etc.)
        if "loadedfiles.org" in href or "obqj2.com" not in href:
            # Try to extract quality and size from filename in URL
            label = text or "Download"
            # Try to parse quality from filename in href
            q_m = re.search(r'\.(\d{3,4}p)\.', href, re.I)
            quality = q_m.group(1) if q_m else ""
            # Try to parse episode from filename
            ep_m = re.search(r'S\d+E\d+', href, re.I) or re.search(r'Episode\.?\s*\d+', href, re.I)
            if ep_m:
                label = f"{ep_m.group(0)}"
            elif quality:
                label = f"Download {quality}"
            else:
                # Try to get filename
                fn_m = re.search(r'/([^/]+\.(?:mkv|mp4|avi))', href)
                if fn_m:
                    fn = fn_m.group(1).replace("%5B", "[").replace("%5D", "]").replace(".", " ")
                    label = fn[:60]
                else:
                    label = f"Download"
            # Filesize lookup — search the page for matching Filesize
            size = ""
            # Look for pattern "Filename: X.mkv\nFilesize: YY MB"
            # The filename in URL may match a filename in the page
            url_filename = href.split("/")[-1].replace("%5B", "[").replace("%5D", "]")
            size_m = re.search(r'Filename:\s*' + re.escape(url_filename[:30]) + r'[^<]*?Filesize:\s*([\d.]+\s*(?:MB|GB))', html)
            if size_m:
                size = size_m.group(1)
            downloads.append({
                "label": label,
                "url": href,
                "quality": quality,
                "size": size,
            })
    data["downloads"] = downloads[:20]  # Keep up to 20 download links

    # Episode thumbnails
    thumbs = []
    for img in re.findall(r'(https?://9jarocks\.net/wp-content/uploads/[^"\s]+_thumb\.jpg)', html):
        if img not in thumbs: thumbs.append(img)
    data["thumbnails"] = thumbs[:12]

    # Related
    related = []
    rel_m = re.search(r'Related Articles(.*?)(?:Read Next|Comments|Leave a Reply|<footer)', html, re.S)
    if rel_m:
        for a in re.finditer(r'<a[^>]+href="(https?://9jarocks\.net/videodownload/[^"]+)"[^>]*>(.*?)</a>', rel_m.group(1), re.S):
            url_r, title_r = a.group(1), strip_tags(a.group(2))
            if title_r and len(title_r) > 3 and url_r != url:
                related.append({"url": url_r, "title": title_r[:200]})
    data["related"] = related[:6]
    return data


# === Main scrape ===
print("Step 1: Collecting movie URLs from all categories...")
all_targets = []
seen_urls = set()
with ThreadPoolExecutor(max_workers=4) as ex:
    futs = {ex.submit(get_category_movies, c["url"], 8): c for c in CATEGORIES}
    for fut in as_completed(futs):
        c = futs[fut]
        try:
            movies = fut.result()
            print(f"  {c['name']}: {len(movies)} movies")
            for m in movies:
                if m["url"] not in seen_urls:
                    seen_urls.add(m["url"])
                    all_targets.append({**m, "category": c["name"], "category_slug": c["slug"]})
        except Exception as e:
            print(f"  {c['name']}: ERROR {e}")
print(f"Total unique movie URLs to fetch: {len(all_targets)}")

print("\nStep 2: Fetching movie details (concurrent)...")
results = []
done_count = [0]
def worker(t):
    try:
        return parse_movie_detail(t["url"], t["title"], t.get("poster"), t["category"], t["category_slug"])
    except Exception as e:
        return {"url": t["url"], "title": t["title"], "poster": t.get("poster"),
                "category": t["category"], "category_slug": t["category_slug"],
                "plot": "", "meta": {}, "downloads": [], "thumbnails": [], "related": [],
                "trailer_url": "", "error": str(e)}

with ThreadPoolExecutor(max_workers=8) as ex:
    futs = [ex.submit(worker, t) for t in all_targets]
    for fut in as_completed(futs):
        d = fut.result()
        with lock:
            results.append(d)
            done_count[0] += 1
            if done_count[0] % 5 == 0:
                with open(OUTPUT, "w", encoding="utf-8") as f:
                    json.dump({"scraped_at": int(time.time()), "source": BASE,
                               "categories": [{"name": c["name"], "slug": c["slug"]} for c in CATEGORIES],
                               "movies": results}, f, indent=2, ensure_ascii=False)
            print(f"  [{done_count[0]}/{len(all_targets)}] {d.get('title','?')[:60]} | DLs: {len(d.get('downloads', []))} | Trailer: {'Y' if d.get('trailer_url') else 'N'}")

# Final save
with open(OUTPUT, "w", encoding="utf-8") as f:
    json.dump({"scraped_at": int(time.time()), "source": BASE,
               "categories": [{"name": c["name"], "slug": c["slug"]} for c in CATEGORIES],
               "movies": results}, f, indent=2, ensure_ascii=False)

# Stats
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
print(f"Saved to {OUTPUT}")
