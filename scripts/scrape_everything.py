#!/usr/bin/env python3
"""
=================================================================
  OentBox — All-in-One Movie Scraper for 9jarocks.net
=================================================================

This single script does EVERYTHING:
  1. Scrapes all movie URLs from all 14 categories (paginated)
  2. Fetches full details for each movie (title, poster, plot, year,
     genre, country, language, duration, trailer, download links,
     episode thumbnails, related movies)
  3. Downloads all poster images locally
  4. Converts posters to WebP format (30-50% smaller)
  5. Seeds the Django database with all scraped data
  6. Prints a summary report

USAGE:
  cd /home/z/my-project
  python scripts/scrape_everything.py                    # Default: 5 pages per category
  python scripts/scrape_everything.py --pages 20         # 20 pages per category (~3,000 movies)
  python scripts/scrape_everything.py --pages 50         # 50 pages per category (~7,000 movies)
  python scripts/scrape_everything.py --pages 0          # ALL pages (may take hours)
  python scripts/scrape_everything.py --skip-posters     # Skip downloading posters
  python scripts/scrape_everything.py --skip-webp        # Skip WebP conversion
  python scripts/scrape_everything.py --skip-seed        # Skip database seeding
  python scripts/scrape_everything.py --categories korean-drama,anime  # Only specific categories

The script is RESUMABLE — it saves progress every 25 movies and
skips movies already scraped. You can stop and restart anytime.

REQUIREMENTS:
  pip install django pillow

=================================================================
"""

import argparse
import json
import os
import re
import sys
import time
import random
import urllib.request
import urllib.parse
import threading
from html import unescape
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---- Configuration ----
BASE = "https://9jarocks.net"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": BASE,
}
PROJECT_DIR = Path(__file__).resolve().parent.parent
DATASET_FILE = PROJECT_DIR / "scripts" / "movies_dataset.json"
DJANGO_DIR = PROJECT_DIR / "moviehub"
POSTERS_DIR = DJANGO_DIR / "media" / "posters"
OUTPUT_LOCK = threading.Lock()
SAVE_EVERY = 25  # Save dataset every N movies

# ---- All 14 categories (niche-first for better categorization) ----
ALL_CATEGORIES = [
    {"name": "Korean Drama", "slug": "korean-drama", "url_slug": "korean-drama"},
    {"name": "Chinese Drama", "slug": "chinese-drama", "url_slug": "chinese-drama"},
    {"name": "Thai Drama", "slug": "thai-drama", "url_slug": "thai-drama"},
    {"name": "Filipino Drama", "slug": "filipino-drama", "url_slug": "filipino-drama"},
    {"name": "Japanese Drama", "slug": "japanese-drama", "url_slug": "japanese-drama"},
    {"name": "Anime", "slug": "anime", "url_slug": "anime"},
    {"name": "Pro Wrestling", "slug": "wrestling", "url_slug": "pro-wrestling-fighting-sports"},
    {"name": "Other Foreign Series", "slug": "other-foreign-series", "url_slug": "other-foreign-series"},
    {"name": "Foreign Movies", "slug": "foreign", "url_slug": "foreign-movies"},
    {"name": "Ongoing Series", "slug": "ongoing", "url_slug": "ongoing"},
    {"name": "Nollywood", "slug": "nollywood", "url_slug": "nollywood-movie"},
    {"name": "Nollywood Series", "slug": "nollywood-series", "url_slug": "nollywood-tv-series"},
    {"name": "Hollywood", "slug": "hollywood", "url_slug": "hollywood-movie"},
    {"name": "Hollywood Series", "slug": "hollywood-series", "url_slug": "hollywood-tv-series"},
]


# ==================================================================
#  NETWORK HELPERS
# ==================================================================

def fetch(url, timeout=20, retries=3):
    """Fetch URL with retry logic."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
            else:
                raise


def download_file(url, dest_path, timeout=30):
    """Download a file (image) to local path. Returns True on success."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
        if len(data) < 500:
            return False  # Too small, probably an error page
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(data)
        return True
    except Exception:
        return False


def strip_tags(s):
    if not s:
        return ""
    s = re.sub(r'<script[^>]*>.*?</script>', '', s, flags=re.S | re.I)
    s = re.sub(r'<style[^>]*>.*?</style>', '', s, flags=re.S | re.I)
    s = re.sub(r'<[^>]+>', ' ', s)
    s = unescape(s)
    return re.sub(r'\s+', ' ', s).strip()


# ==================================================================
#  STEP 1: COLLECT MOVIE URLs FROM CATEGORY PAGES
# ==================================================================

def get_category_movies(cat_url, cat_slug, max_pages):
    """Scrape movie URLs from a category page (paginated)."""
    all_movies = []
    seen = set()
    page = 1
    while True:
        if max_pages > 0 and page > max_pages:
            break
        url = cat_url if page == 1 else f"{cat_url}/page/{page}"
        try:
            html = fetch(url)
        except Exception as e:
            print(f"    page {page}: ERROR {e}")
            break

        page_movies = []
        for m in re.finditer(r'<a[^>]+href="(https?://9jarocks\.net/videodownload/[^"]+-id\d+\.html)"[^>]*>(.*?)</a>', html, re.S):
            link = m.group(1)
            if '#comment-' in link:
                continue
            text = strip_tags(m.group(2))
            if not text or len(text) < 4 or text.lower().startswith('download'):
                continue
            if link in seen:
                continue
            seen.add(link)
            page_movies.append({"url": link, "title": text[:200], "poster": None})

        # Extract posters from article blocks
        poster_map = {}
        for art in re.findall(r'<article[^>]*>(.*?)</article>', html, re.S):
            lm = re.search(r'<a[^>]+href="(https?://9jarocks\.net/videodownload/[^"]+-id\d+\.html)"', art)
            if not lm:
                continue
            u = lm.group(1)
            if u in poster_map:
                continue
            im = re.search(r'<img[^>]+src="(https?://9jarocks\.net/wp-content/uploads/[^"]+)"', art)
            if not im:
                im = re.search(r'<img[^>]+data-src="(https?://9jarocks\.net/wp-content/uploads/[^"]+)"', art)
            if im:
                poster_map[u] = im.group(1)

        for pm in page_movies:
            pm["poster"] = poster_map.get(pm["url"])

        # Prefer category-specific URLs
        preferred = [pm for pm in page_movies if cat_slug in pm["url"].lower() or cat_slug.replace('-', ' ') in pm["title"].lower()]
        others = [pm for pm in page_movies if pm not in preferred]
        all_movies.extend(preferred + others)

        print(f"    page {page}: {len(page_movies)} movies")

        if not page_movies:
            break
        if f'/page/{page + 1}' not in html:
            break
        page += 1
        time.sleep(0.3)

    return all_movies


# ==================================================================
#  STEP 2: PARSE MOVIE DETAIL PAGES
# ==================================================================

def parse_movie_detail(url, fallback_title=None, fallback_poster=None, category=None, category_slug=None):
    """Parse a movie detail page and extract all metadata."""
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
                poster = img
                break
    data["poster"] = poster or fallback_poster

    # Trailer (YouTube embed)
    trailer_url = ""
    yt = re.search(r'<iframe[^>]*src="(https://www\.youtube\.com/embed/[^"]+)"', html)
    if not yt:
        yt = re.search(r'<iframe[^>]*src="(https://youtube\.com/embed/[^"]+)"', html)
    if yt:
        trailer_url = yt.group(1).split("?")[0]
    data["trailer_url"] = trailer_url

    # Plot
    plot = ""
    for p in re.findall(r'<p[^>]*>(.*?)</p>', html, re.S):
        txt = strip_tags(p)
        if len(txt) > 80 and not txt.lower().startswith("filename") and "filesize" not in txt.lower():
            plot = txt
            break
    data["plot"] = plot[:1500]

    # Metadata fields
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

    # Download links (real file-host URLs from loadedfiles.org)
    downloads = []
    for m in re.finditer(r'<a[^>]*class="[^"]*fa-fa-download[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        href = m.group(1)
        text = strip_tags(m.group(2))
        # Skip ad-network links
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
        # Filesize lookup
        size = ""
        url_filename = href.split("/")[-1].replace("%5B", "[").replace("%5D", "]")
        size_m = re.search(r'Filename:\s*' + re.escape(url_filename[:30]) + r'[^<]*?Filesize:\s*([\d.]+\s*(?:MB|GB))', html)
        if size_m:
            size = size_m.group(1)
        downloads.append({"label": label, "url": href, "quality": quality, "size": size})
    data["downloads"] = downloads[:30]

    # Episode thumbnails
    thumbs = list(dict.fromkeys(re.findall(r'(https?://9jarocks\.net/wp-content/uploads/[^"\s]+_thumb\.jpg)', html)))
    data["thumbnails"] = thumbs[:12]

    # Related movies
    related = []
    rel_m = re.search(r'Related Articles(.*?)(?:Read Next|Comments|Leave a Reply|<footer)', html, re.S)
    if rel_m:
        for a in re.finditer(r'<a[^>]+href="(https?://9jarocks\.net/videodownload/[^"]+)"[^>]*>(.*?)</a>', rel_m.group(1), re.S):
            t = strip_tags(a.group(2))
            if t and len(t) > 3 and a.group(1) != url:
                related.append({"url": a.group(1), "title": t[:200]})
    data["related"] = related[:6]

    return data


# ==================================================================
#  STEP 3: DOWNLOAD POSTERS LOCALLY
# ==================================================================

def download_poster(url, slug):
    """Download a poster image locally. Returns local /media/ URL or original URL on failure."""
    if not url:
        return ""
    if url.startswith("/media/"):
        return url  # Already local
    # Determine extension
    ext = ".jpg"
    for e in (".webp", ".png", ".jpg", ".jpeg", ".gif"):
        if e in url.lower():
            ext = e
            break
    local_path = POSTERS_DIR / f"{slug}{ext}"
    rel_url = f"/media/posters/{slug}{ext}"
    if local_path.exists():
        return rel_url  # Already downloaded
    if download_file(url, local_path):
        return rel_url
    return url  # Fallback to remote URL


# ==================================================================
#  STEP 4: CONVERT POSTERS TO WebP
# ==================================================================

def convert_to_webp():
    """Convert all downloaded posters to WebP format."""
    try:
        from PIL import Image
    except ImportError:
        print("  [WebP] Pillow not installed, skipping conversion")
        return 0

    if not POSTERS_DIR.exists():
        return 0

    extensions = (".jpg", ".jpeg", ".png")
    images = []
    for ext in extensions:
        images.extend(POSTERS_DIR.glob(f"*{ext}"))
        images.extend(POSTERS_DIR.glob(f"*{ext.upper()}"))

    converted = 0
    total_saved = 0
    for img_path in images:
        try:
            with Image.open(img_path) as img:
                if img.width > 400:
                    new_height = int(img.height * (400 / img.width))
                    img = img.resize((400, new_height), Image.LANCZOS)
                webp_path = img_path.with_suffix(".webp")
                img.save(webp_path, "WEBP", quality=80, method=6)
                original_size = img_path.stat().st_size
                webp_size = webp_path.stat().st_size
                if webp_size > 0:
                    total_saved += original_size - webp_size
                    img_path.unlink()
                    converted += 1
        except Exception:
            pass

    if converted > 0:
        print(f"  [WebP] Converted {converted} images, saved {total_saved / (1024*1024):.1f} MB")
    return converted


# ==================================================================
#  STEP 5: SEED DJANGO DATABASE
# ==================================================================

CATEGORY_META = {
    "nollywood": {"name": "Nollywood", "icon": "🎬", "order": 1},
    "nollywood-series": {"name": "Nollywood Series", "icon": "📺", "order": 2},
    "hollywood": {"name": "Hollywood", "icon": "🍿", "order": 3},
    "hollywood-series": {"name": "Hollywood Series", "icon": "🎞️", "order": 4},
    "foreign": {"name": "Foreign Movies", "icon": "🌍", "order": 5},
    "other-foreign-series": {"name": "Other Foreign Series", "icon": "🌠", "order": 6},
    "korean-drama": {"name": "Korean Drama", "icon": "🇰🇷", "order": 7},
    "chinese-drama": {"name": "Chinese Drama", "icon": "🇨🇳", "order": 8},
    "thai-drama": {"name": "Thai Drama", "icon": "🇹🇭", "order": 9},
    "filipino-drama": {"name": "Filipino Drama", "icon": "🇵🇭", "order": 10},
    "japanese-drama": {"name": "Japanese Drama", "icon": "🇯🇵", "order": 11},
    "anime": {"name": "Anime", "icon": "🌸", "order": 12},
    "wrestling": {"name": "Pro Wrestling", "icon": "🤼", "order": 13},
    "ongoing": {"name": "Ongoing Series", "icon": "🔴", "order": 14},
}


def seed_database(dataset):
    """Seed the Django database with all scraped movies."""
    # Setup Django
    sys.path.insert(0, str(DJANGO_DIR))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django
    django.setup()
    from movies.models import Category, Genre, Movie, DownloadLink, EpisodeThumbnail
    from django.utils.text import slugify

    # Create all categories
    for slug, meta in CATEGORY_META.items():
        Category.objects.update_or_create(
            slug=slug,
            defaults={
                "name": meta["name"],
                "icon": meta["icon"],
                "order": meta["order"],
                "is_active": True,
                "description": f"{meta['name']} — latest releases, fresh downloads, HD quality.",
            },
        )
    cat_lookup = {c.slug: c for c in Category.objects.all()}
    print(f"  [Seed] {len(cat_lookup)} categories ready")

    movies_data = dataset.get("movies", [])
    print(f"  [Seed] Processing {len(movies_data)} movies...")

    # Clear existing movies
    Movie.objects.all().delete()
    print(f"  [Seed] Cleared existing movies")

    created_count = 0
    genre_cache = {}

    def get_genres(genre_str):
        if not genre_str:
            return []
        parts = [g.strip().title() for g in re.split(r'[,/&]| - | and ', genre_str) if g.strip()]
        out = []
        for p in parts:
            if p and p not in genre_cache:
                genre_cache[p], _ = Genre.objects.get_or_create(name=p)
            if p:
                out.append(genre_cache[p])
        return out

    for i, entry in enumerate(movies_data):
        meta = entry.get("meta", {}) or {}
        cat = cat_lookup.get(entry.get("category_slug"))
        title = entry.get("title", "").strip()
        if not title:
            continue

        # Determine status
        status = "Released"
        if "(complete)" in title.lower():
            status = "Complete"
        elif "episode" in title.lower() and "added" in title.lower():
            status = "Ongoing"

        # Determine movie type
        movie_type = meta.get("type", "Movie") or "Movie"
        cs = entry.get("category_slug", "")
        if cs == "anime":
            movie_type = "Anime"
        elif cs == "wrestling":
            movie_type = "Sports"
        elif cs in ("nollywood-series", "hollywood-series"):
            if "series" not in movie_type.lower():
                movie_type = "TV Series"
        elif cs == "korean-drama":
            movie_type = "K-Drama"

        # Year
        year = None
        try:
            year = int(meta.get("year")) if meta.get("year") else None
        except (ValueError, TypeError):
            year = None

        # Poster
        poster = entry.get("poster") or ""

        # Plot
        plot = (entry.get("plot") or "").strip()
        if not plot:
            plot = f"{title} — available now in HD. Stream or download from OentBox."

        movie = Movie.objects.create(
            title=title,
            category=cat,
            poster_url=poster,
            backdrop_url=poster,
            plot=plot,
            year=year,
            country=meta.get("country", ""),
            language=meta.get("language", ""),
            movie_type=movie_type,
            duration=meta.get("duration", ""),
            imdb_url=meta.get("imdb_url", ""),
            trailer_url=entry.get("trailer_url", ""),
            status=status,
            rating=round(random.uniform(5.5, 9.4), 1),
            quality=random.choice(["HD", "HD", "1080p", "720p", "4K"]),
            views=random.randint(120, 98000),
        )
        created_count += 1

        # Genres
        gs = get_genres(meta.get("genre", ""))
        if gs:
            movie.genres.set(gs)

        # Download links
        real_dls = entry.get("downloads", [])
        AD_DOMAINS = ("obqj2.com", "associationfoam.com", "googlesyndication", "doubleclick")
        filtered_dls = [dl for dl in real_dls if dl.get("url") and not any(ad in dl["url"] for ad in AD_DOMAINS)]
        for j, dl in enumerate(filtered_dls):
            DownloadLink.objects.create(
                movie=movie,
                label=(dl.get("label") or "Download")[:120],
                url=dl["url"],
                quality=dl.get("quality", ""),
                size=dl.get("size", ""),
                order=j,
            )

        # Episode thumbnails
        for j, turl in enumerate(entry.get("thumbnails", [])[:6]):
            EpisodeThumbnail.objects.create(
                movie=movie,
                image_url=turl,
                caption=f"Scene {j+1}" if "episode" in title.lower() else "",
                order=j,
            )

        if (i + 1) % 500 == 0:
            print(f"    [{i+1}/{len(movies_data)}] Seeded...")

    # Set flags
    all_movies = list(Movie.objects.all())
    for m in random.sample(all_movies, min(6, len(all_movies))):
        m.is_featured = True
        m.save(update_fields=["is_featured"])
    for m in random.sample([m for m in all_movies if (m.rating or 0) >= 8.0], min(10, len([m for m in all_movies if (m.rating or 0) >= 8.0]))):
        m.is_trending = True
        m.save(update_fields=["is_trending"])
    for m in random.sample(all_movies, min(8, len(all_movies))):
        m.is_new_release = True
        m.save(update_fields=["is_new_release"])

    print(f"  [Seed] Created {created_count} movies, {DownloadLink.objects.count()} download links")
    return created_count


# ==================================================================
#  DATASET SAVE/LOAD
# ==================================================================

def load_dataset():
    """Load existing dataset (for resume capability)."""
    if DATASET_FILE.exists():
        try:
            decoder = json.JSONDecoder()
            with open(DATASET_FILE, "r", encoding="utf-8") as f:
                content = f.read()
            data, _ = decoder.raw_decode(content)
            return data
        except Exception:
            pass
    return {
        "scraped_at": int(time.time()),
        "source": BASE,
        "categories": [{"name": c["name"], "slug": c["slug"]} for c in ALL_CATEGORIES],
        "movies": [],
    }


def save_dataset(data):
    """Save dataset atomically."""
    tmp = str(DATASET_FILE) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.rename(tmp, DATASET_FILE)


# ==================================================================
#  MAIN
# ==================================================================

def main():
    parser = argparse.ArgumentParser(description="OentBox — All-in-One Movie Scraper for 9jarocks.net")
    parser.add_argument("--pages", type=int, default=5, help="Pages per category (0 = all pages, default 5)")
    parser.add_argument("--skip-posters", action="store_true", help="Skip downloading poster images")
    parser.add_argument("--skip-webp", action="store_true", help="Skip WebP conversion")
    parser.add_argument("--skip-seed", action="store_true", help="Skip database seeding")
    parser.add_argument("--categories", type=str, default="", help="Comma-separated category slugs (default: all)")
    parser.add_argument("--workers", type=int, default=6, help="Concurrent download workers (default 6)")
    args = parser.parse_args()

    print("=" * 60)
    print("  OentBox — All-in-One Movie Scraper")
    print("=" * 60)
    print(f"  Pages per category: {'ALL' if args.pages == 0 else args.pages}")
    print(f"  Download posters: {'No' if args.skip_posters else 'Yes'}")
    print(f"  Convert to WebP: {'No' if args.skip_webp else 'Yes'}")
    print(f"  Seed database: {'No' if args.skip_seed else 'Yes'}")
    print(f"  Workers: {args.workers}")
    print()

    # Filter categories if specified
    cats_to_scrape = ALL_CATEGORIES
    if args.categories:
        selected = [s.strip() for s in args.categories.split(",")]
        cats_to_scrape = [c for c in ALL_CATEGORIES if c["slug"] in selected]
        if not cats_to_scrape:
            print(f"ERROR: No matching categories found for: {args.categories}")
            print(f"Available: {', '.join(c['slug'] for c in ALL_CATEGORIES)}")
            return

    # Load existing dataset
    dataset = load_dataset()
    existing_urls = {m["url"] for m in dataset["movies"]}
    print(f"Resuming: {len(dataset['movies'])} movies already in dataset\n")

    # ---- STEP 1: Collect URLs ----
    print("=" * 60)
    print("  STEP 1: Collecting movie URLs from all categories")
    print("=" * 60)
    all_targets = []
    seen_urls = set(existing_urls)
    for c in cats_to_scrape:
        cat_url = f"{BASE}/category/videodownload/{c['url_slug']}"
        print(f"\n  {c['name']}:")
        try:
            cat_movies = get_category_movies(cat_url, c["slug"], args.pages)
            new_count = 0
            for m in cat_movies:
                if m["url"] not in seen_urls:
                    seen_urls.add(m["url"])
                    all_targets.append({**m, "category": c["name"], "category_slug": c["slug"]})
                    new_count += 1
            print(f"    -> {new_count} new movies")

            # Save URLs immediately (resume safety)
            with OUTPUT_LOCK:
                for m in cat_movies:
                    if m["url"] not in {e["url"] for e in dataset["movies"]}:
                        dataset["movies"].append({
                            "url": m["url"], "title": m["title"], "poster": m.get("poster"),
                            "category": c["name"], "category_slug": c["slug"],
                            "plot": "", "meta": {}, "downloads": [],
                            "thumbnails": [], "related": [], "trailer_url": "",
                        })
                save_dataset(dataset)
                existing_urls = {m["url"] for m in dataset["movies"]}
        except Exception as e:
            print(f"    ERROR: {e}")

    print(f"\n  Total new movies to fetch: {len(all_targets)}")

    # ---- STEP 2: Fetch details ----
    if all_targets:
        print("\n" + "=" * 60)
        print(f"  STEP 2: Fetching movie details ({len(all_targets)} movies)")
        print("=" * 60)
        results = list(dataset["movies"])
        done_count = [0]
        total = len(all_targets)

        def worker(t):
            try:
                d = parse_movie_detail(t["url"], t["title"], t.get("poster"), t["category"], t["category_slug"])
                # Download poster if not skipped
                if not args.skip_posters and d.get("poster"):
                    from django.utils.text import slugify
                    base_slug = slugify(d.get("title", ""))[:250] or f"movie-{t['url'].split('-id')[-1].split('.')[0]}"
                    local_poster = download_poster(d["poster"], base_slug)
                    if local_poster:
                        d["poster"] = local_poster
                return d
            except Exception as e:
                return {"url": t["url"], "title": t["title"], "poster": t.get("poster"),
                        "category": t["category"], "category_slug": t["category_slug"],
                        "plot": "", "meta": {}, "downloads": [], "thumbnails": [],
                        "related": [], "trailer_url": "", "error": str(e)}

        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(worker, t) for t in all_targets]
            for fut in as_completed(futs):
                d = fut.result()
                with OUTPUT_LOCK:
                    # Update dataset with full details
                    url_to_result = {d["url"]: d}
                    for m in dataset["movies"]:
                        if m["url"] == d["url"] and not m.get("plot"):
                            m.update(d)
                            break
                    else:
                        dataset["movies"].append(d)

                    done_count[0] += 1
                    if done_count[0] % SAVE_EVERY == 0:
                        save_dataset(dataset)
                    if done_count[0] % 10 == 0:
                        print(f"    [{done_count[0]}/{total}] {d.get('title','?')[:50]} | DLs:{len(d.get('downloads',[]))} | Tr:{'Y' if d.get('trailer_url') else 'N'}")

        save_dataset(dataset)

    # ---- STEP 3: Convert to WebP ----
    if not args.skip_webp and not args.skip_posters:
        print("\n" + "=" * 60)
        print("  STEP 3: Converting posters to WebP")
        print("=" * 60)
        convert_to_webp()
    elif args.skip_posters:
        print("\n  [SKIP] Poster download and WebP conversion skipped")

    # ---- STEP 4: Seed database ----
    if not args.skip_seed:
        print("\n" + "=" * 60)
        print("  STEP 4: Seeding Django database")
        print("=" * 60)
        seed_database(dataset)
    else:
        print("\n  [SKIP] Database seeding skipped")

    # ---- SUMMARY ----
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    with_poster = sum(1 for m in dataset["movies"] if m.get("poster"))
    with_plot = sum(1 for m in dataset["movies"] if m.get("plot"))
    with_downloads = sum(1 for m in dataset["movies"] if m.get("downloads"))
    with_trailer = sum(1 for m in dataset["movies"] if m.get("trailer_url"))
    total_dls = sum(len(m.get("downloads", [])) for m in dataset["movies"])
    poster_count = len(list(POSTERS_DIR.glob("*"))) if POSTERS_DIR.exists() else 0

    print(f"  Total movies scraped: {len(dataset['movies'])}")
    print(f"  With poster: {with_poster}")
    print(f"  With plot: {with_plot}")
    print(f"  With downloads: {with_downloads} ({total_dls} total links)")
    print(f"  With trailer: {with_trailer}")
    print(f"  Posters on disk: {poster_count}")
    print(f"  Dataset saved to: {DATASET_FILE}")
    print()
    from collections import Counter
    cats = Counter(m.get("category_slug", "?") for m in dataset["movies"])
    print("  Movies per category:")
    for slug, n in sorted(cats.items()):
        print(f"    {slug}: {n}")
    print()
    print("=" * 60)
    print("  DONE!")
    print("=" * 60)


if __name__ == "__main__":
    main()
