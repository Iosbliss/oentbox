#!/usr/bin/env python3
"""Fix movies with missing posters by re-scraping their detail pages."""
import os
import sys
import re
import json
import urllib.request
from html import unescape

BASE = "https://9jarocks.net"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"}
DATASET = "/home/z/my-project/scripts/movies_dataset.json"

sys.path.insert(0, '/home/z/my-project/moviehub')
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
import django; django.setup()
from movies.models import Movie


def fetch(url, timeout=20):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except:
            if attempt < 2:
                import time; time.sleep(2)
            else:
                raise


def extract_poster(html):
    """Extract poster URL from a movie detail page."""
    # Try og:image first
    m = re.search(r'<meta property="og:image"\s+content="([^"]+)"', html)
    if m:
        return m.group(1)
    # Try first content image (skip base64, download buttons, thumbs)
    for img in re.findall(r'<img[^>]+src="(https?://9jarocks\.net/wp-content/uploads/[^"]+)"', html):
        if "Download-Button" not in img and "thumb" not in img.lower():
            return img
    # Try any wp-content image
    for img in re.findall(r'<img[^>]+src="(https?://[^"]+)"', html):
        if "wp-content/uploads" in img and "Download-Button" not in img and "thumb" not in img.lower():
            return img
    return ""


def extract_trailer(html):
    """Extract YouTube trailer URL."""
    yt = re.search(r'<iframe[^>]*src="(https://www\.youtube\.com/embed/[^"]+)"', html)
    if yt:
        return yt.group(1).split("?")[0]
    return ""


# Find all movies with no poster
movies_no_poster = list(Movie.objects.filter(poster_url=''))
print(f"Found {len(movies_no_poster)} movies with no poster")

fixed = 0
failed = 0
for i, movie in enumerate(movies_no_poster):
    if not movie.source_url:
        continue
    try:
        html = fetch(movie.source_url)
        poster = extract_poster(html)
        trailer = extract_trailer(html)

        if poster:
            movie.poster_url = poster
            movie.backdrop_url = poster
            if trailer and not movie.trailer_url:
                movie.trailer_url = trailer
            movie.save(update_fields=['poster_url', 'backdrop_url', 'trailer_url'])
            fixed += 1
            if fixed % 10 == 0:
                print(f"  [{fixed}/{len(movies_no_poster)}] Fixed: {movie.title[:50]}")
        else:
            failed += 1

        # Also update the dataset JSON
        if poster:
            try:
                with open(DATASET, 'r', encoding='utf-8') as f:
                    dataset = json.load(f)
                for m in dataset['movies']:
                    if m.get('url') == movie.source_url:
                        m['poster'] = poster
                        if trailer:
                            m['trailer_url'] = trailer
                        break
                with open(DATASET, 'w', encoding='utf-8') as f:
                    json.dump(dataset, f, indent=2, ensure_ascii=False)
            except:
                pass

    except Exception as e:
        failed += 1
        if failed <= 5:
            print(f"  Failed: {movie.title[:50]} - {e}")

print(f"\n=== DONE ===")
print(f"Fixed: {fixed}")
print(f"Failed: {failed}")
print(f"Movies with poster now: {Movie.objects.exclude(poster_url='').count()}")
print(f"Movies still without poster: {Movie.objects.filter(poster_url='').count()}")
