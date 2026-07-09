"""Seed database from scraped movies_dataset.json."""
import json
import os
import random
import re
import urllib.request
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from movies.models import Category, Genre, Movie, DownloadLink, EpisodeThumbnail

DATASET = Path("/home/z/my-project/scripts/movies_dataset.json")
POSTERS_DIR = Path(settings.MEDIA_ROOT) / "posters"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Referer": "https://9jarocks.net/",
}


def download_poster(url, slug):
    """Download poster locally; return local MEDIA-relative URL or original URL on failure."""
    if not url:
        return ""
    # Already local?
    if url.startswith("/media/"):
        return url
    ext = ".jpg"
    for e in (".webp", ".png", ".jpg", ".jpeg", ".gif"):
        if e in url.lower():
            ext = e
            break
    local_path = POSTERS_DIR / f"{slug}{ext}"
    rel_url = f"/media/posters/{slug}{ext}"
    if local_path.exists():
        return rel_url  # already downloaded
    try:
        POSTERS_DIR.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
        if len(data) < 500:
            return url  # too small, probably error page
        with open(local_path, "wb") as f:
            f.write(data)
        return rel_url
    except Exception as e:
        # Fallback to original URL
        return url

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


class Command(BaseCommand):
    help = "Seed the database from scraped movies_dataset.json"

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-posters",
            action="store_true",
            help="Skip downloading posters locally (use remote URLs instead — much faster)",
        )

    def handle(self, *args, **opts):
        if not DATASET.exists():
            self.stderr.write(self.style.ERROR(f"Dataset not found at {DATASET}"))
            return

        with open(DATASET, encoding="utf-8") as f:
            data = json.load(f)

        # Create ALL 14 categories from CATEGORY_META (ensures all categories exist)
        for slug, meta in CATEGORY_META.items():
            Category.objects.update_or_create(
                slug=slug,
                defaults={
                    "name": meta.get("name", slug.replace("-", " ").title()),
                    "icon": meta["icon"],
                    "order": meta["order"],
                    "is_active": True,
                    "description": f"{meta.get('name', slug.replace('-', ' ').title())} — latest releases, fresh downloads, HD quality.",
                },
            )
        # Also create any categories from the dataset that aren't in CATEGORY_META
        for c in data.get("categories", []):
            slug = c["slug"]
            if slug not in CATEGORY_META:
                Category.objects.update_or_create(
                    slug=slug,
                    defaults={
                        "name": c["name"],
                        "icon": "🎬",
                        "order": 99,
                        "is_active": True,
                        "description": f"{c['name']} — latest releases, fresh downloads, HD quality.",
                    },
                )

        cat_lookup = {c.slug: c for c in Category.objects.all()}
        self.stdout.write(f"Created/updated {len(cat_lookup)} categories")

        # Reset movie flags — we will recompute
        Movie.objects.all().update(is_featured=False, is_trending=False, is_new_release=False)

        # Genre splitter
        genre_cache = {}

        def get_genres(genre_str):
            if not genre_str:
                return []
            parts = [g.strip().title() for g in re_split(genre_str) if g.strip()]
            out = []
            for p in parts:
                if p and p not in genre_cache:
                    genre_cache[p], _ = Genre.objects.get_or_create(name=p)
                if p:
                    out.append(genre_cache[p])
            return out

        def re_split(s):
            import re
            return re.split(r"[,/&]| - | and ", s)

        movies_created = 0
        movies_updated = 0
        all_movies_for_flags = []

        for entry in data.get("movies", []):
            meta = entry.get("meta", {}) or {}
            cat = cat_lookup.get(entry.get("category_slug"))
            year = None
            try:
                year = int(meta.get("year")) if meta.get("year") else None
            except (ValueError, TypeError):
                year = None

            # Determine status from title
            title = entry.get("title", "").strip()
            status = "Released"
            if "(complete)" in title.lower():
                status = "Complete"
            elif "episode" in title.lower() and "added" in title.lower():
                status = "Ongoing"
            elif "(ongoing" in title.lower():
                status = "Ongoing"

            movie_type = meta.get("type", "Movie") or "Movie"
            # Refine movie_type based on category
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

            # Build a clean plot
            plot = (entry.get("plot") or "").strip()
            if not plot:
                plot = f"{title} — available now in HD. Stream or download from MovieHub."

            poster = entry.get("poster") or ""

            # Download poster locally for self-contained app
            slug_seed = Movie.objects.filter(source_url=entry.get("url", "")).first()
            slug_for_download = slug_seed.slug if slug_seed else ""
            if not slug_for_download:
                # Generate the slug the same way the model would
                from django.utils.text import slugify
                base = slugify(title)[:250]
                slug_for_download = base or f"movie-{entry.get('url', '').split('-id')[-1].split('.')[0]}"

            if opts.get("skip_posters"):
                local_poster = poster
            else:
                local_poster = download_poster(poster, slug_for_download) if poster else ""

            movie, created = Movie.objects.update_or_create(
                source_url=entry.get("url", ""),
                defaults={
                    "title": title,
                    "category": cat,
                    "poster_url": local_poster or poster,
                    "backdrop_url": local_poster or poster,  # use poster as backdrop fallback
                    "plot": plot,
                    "year": year,
                    "country": meta.get("country", ""),
                    "language": meta.get("language", ""),
                    "movie_type": movie_type,
                    "duration": meta.get("duration", ""),
                    "imdb_url": meta.get("imdb_url", ""),
                    "trailer_url": entry.get("trailer_url", ""),
                    "status": status,
                    "rating": round(random.uniform(5.5, 9.4), 1),
                    "quality": random.choice(["HD", "HD", "1080p", "720p", "4K"]),
                },
            )
            if created:
                movies_created += 1
            else:
                movies_updated += 1

            # Genres
            gs = get_genres(meta.get("genre", ""))
            if gs:
                movie.genres.set(gs)

            # Use REAL download links from scraper; only fall back to synthetic if none
            movie.download_links.all().delete()
            real_dls = entry.get("downloads", [])
            # Filter out ad-network links — only keep real file-host URLs
            AD_DOMAINS = ("obqj2.com", "associationfoam.com", "googlesyndication", "doubleclick")
            filtered_dls = [dl for dl in real_dls
                            if dl.get("url") and not any(ad in dl["url"] for ad in AD_DOMAINS)]
            if filtered_dls:
                for i, dl in enumerate(filtered_dls):
                    url = dl.get("url", "")
                    label = dl.get("label") or "Download"
                    quality = dl.get("quality", "")
                    size = dl.get("size", "")
                    # If quality not parsed, try to infer from label/URL
                    if not quality:
                        q_m = re.search(r'(\d{3,4}p)', label + " " + url, re.I)
                        if q_m:
                            quality = q_m.group(1)
                    DownloadLink.objects.create(
                        movie=movie,
                        label=label[:120],
                        url=url,
                        quality=quality,
                        size=size,
                        order=i,
                    )
            else:
                # Fallback: synthetic links pointing to source page (last resort)
                base_quality = ["480p", "720p", "1080p"]
                for i, q in enumerate(base_quality):
                    size = f"{random.randint(180, 480)} MB" if q == "480p" else (
                        f"{random.randint(550, 950)} MB" if q == "720p" else f"{random.randint(1, 2)}.{random.randint(1, 9)} GB"
                    )
                    DownloadLink.objects.create(
                        movie=movie,
                        label=f"Download {q}",
                        url=movie.source_url or "#",
                        quality=q,
                        size=size,
                        order=i,
                    )

            # Episode thumbnails
            movie.thumbnails.all().delete()
            for i, turl in enumerate(entry.get("thumbnails", [])[:6]):
                EpisodeThumbnail.objects.create(
                    movie=movie,
                    image_url=turl,
                    caption=f"Scene {i+1}" if "episode" in title.lower() else "",
                    order=i,
                )

            all_movies_for_flags.append(movie)

        # Pick flags deterministically — first 6 most recent = new releases,
        # 8 random with rating >= 8 = trending, 5 with year 2025/2026 = featured
        new_releases = sorted(all_movies_for_flags, key=lambda m: m.created_at, reverse=True)[:8]
        for m in new_releases:
            m.is_new_release = True
            m.save(update_fields=["is_new_release"])

        trending_pool = [m for m in all_movies_for_flags if (m.rating or 0) >= 8.0]
        random.seed(42)
        for m in random.sample(trending_pool, min(10, len(trending_pool))):
            m.is_trending = True
            m.save(update_fields=["is_trending"])

        featured_pool = [m for m in all_movies_for_flags if m.year and m.year >= 2024]
        for m in random.sample(featured_pool, min(6, len(featured_pool))):
            m.is_featured = True
            m.save(update_fields=["is_featured"])

        # Bump view counts randomly for realism
        for m in all_movies_for_flags:
            m.views = random.randint(120, 98000)
            m.save(update_fields=["views"])

        self.stdout.write(self.style.SUCCESS(
            f"Done. Created {movies_created} new, updated {movies_updated}. "
            f"Total movies: {Movie.objects.count()}. "
            f"Genres: {Genre.objects.count()}. "
            f"Categories: {Category.objects.count()}."
        ))
