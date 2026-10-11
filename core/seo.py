"""SEO helpers for oentbox: a chunked sitemap and schema.org structured data.

The catalog holds tens of thousands of titles, so /sitemap.xml is a sitemap
index that points at /sitemap-<n>.xml chunks instead of a single truncated
file. Generated XML is cached because crawlers fetch these repeatedly.
"""
import math
from urllib.parse import quote
from xml.sax.saxutils import escape

from django.core.cache import cache
from django.http import Http404, HttpResponse

from .models import Movie
from .movie_data import EXCLUDED_CATEGORIES

SITEMAP_CHUNK_SIZE = 5000
SITEMAP_CACHE_TTL = 3600
SITEMAP_MAX_AGE = 3600
STATIC_PATHS = ("/", "/about.html", "/privacy.html", "/terms.html", "/browse.html?cat=all", "/youtube.html")


def _base_url(request):
    return request.build_absolute_uri("/").rstrip("/")


def _clean_url(movie_id):
    """Build the SEO-friendly canonical URL for a movie."""
    return "/m/" + str(quote(str(movie_id), safe=""))


def sitemap_index(request):
    """Sitemap index listing one entry per title chunk."""
    total = Movie.objects.exclude(category__in=EXCLUDED_CATEGORIES).count()
    chunks = max(1, math.ceil(total / SITEMAP_CHUNK_SIZE))
    base = escape(_base_url(request))
    body = "".join(
        "<sitemap><loc>%s/sitemap-%d.xml</loc></sitemap>" % (base, number)
        for number in range(1, chunks + 1)
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</sitemapindex>' % body
    )
    response = HttpResponse(xml, content_type="application/xml")
    response["Cache-Control"] = "public, max-age=%d" % SITEMAP_MAX_AGE
    return response


def sitemap_chunk(request, chunk):
    """One title sitemap file: static pages plus up to SITEMAP_CHUNK_SIZE titles."""
    if chunk < 1:
        raise Http404("no such sitemap chunk")
    base = escape(_base_url(request))
    cache_key = "sitemap:chunk:v2:%s:%d" % (base, chunk)
    xml = cache.get(cache_key)
    if xml is None:
        start = (chunk - 1) * SITEMAP_CHUNK_SIZE
        rows = (
            Movie.objects.exclude(category__in=EXCLUDED_CATEGORIES)
            .values("id", "scraped_at")
            .order_by("-scraped_at")[start:start + SITEMAP_CHUNK_SIZE]
        )
        urls = []
        if chunk == 1:
            urls.extend(
                "<url><loc>%s%s</loc></url>" % (base, escape(path)) for path in STATIC_PATHS
            )
        for row in rows:
            lastmod = ""
            if row["scraped_at"]:
                lastmod = "<lastmod>%s</lastmod>" % row["scraped_at"].date().isoformat()
            urls.append(
                '<url><loc>%s%s</loc>%s</url>'
                % (base, escape(_clean_url(row["id"])), lastmod)
            )
        if not urls:
            raise Http404("sitemap chunk is empty")
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</urlset>' % "".join(urls)
        )
        cache.set(cache_key, xml, SITEMAP_CACHE_TTL)
    response = HttpResponse(xml, content_type="application/xml")
    response["Cache-Control"] = "public, max-age=%d" % SITEMAP_MAX_AGE
    return response


def build_movie_schema(movie, request=None):
    """schema.org Movie/TVSeries data for a title detail page."""
    if not movie:
        return {}
    category = str(movie.get("category") or "").lower()
    title = str(movie.get("title") or "")
    lowered = title.lower()
    is_series = "series" in category or any(
        token in lowered for token in ("season", "episode", "series")
    )
    schema = {
        "@context": "https://schema.org",
        "@type": "TVSeries" if is_series else "Movie",
        "name": title,
    }
    if request is not None:
        movie_id = quote(str(movie.get("id", "")), safe="")
        schema["url"] = request.build_absolute_uri(_clean_url(movie_id))
    description = (movie.get("description") or "").strip()
    if description:
        schema["description"] = description[:500]
    images = []
    if movie.get("thumbnail"):
        images.append(movie["thumbnail"])
    images.extend(url for url in (movie.get("screenshots") or [])[:4] if url)
    if images:
        schema["image"] = images if len(images) > 1 else images[0]
    year = movie.get("year")
    if year:
        schema["datePublished"] = str(year)
        schema["dateCreated"] = str(year)
    if category:
        schema["genre"] = category.replace("-", " ").title()

    trailer = None
    if movie.get("trailer_embed_url"):
        # Extract YouTube video ID from embed URL for richer VideoObject schema
        trailer = movie["trailer_embed_url"]
    elif movie.get("trailer_url"):
        trailer = movie["video_url"] if movie.get("video_url") else movie.get("trailer_url")
    if trailer:
        schema["trailer"] = {"@type": "VideoObject", "url": trailer, "name": title + " Trailer"}

    if movie.get("imdb_id"):
        schema["sameAs"] = "https://www.imdb.com/title/" + movie["imdb_id"]
    return schema


def build_breadcrumbs(movie, request=None, category=None):
    """Build breadcrumb schema.org data for a title detail page."""
    if not movie:
        return {}
    base = request.build_absolute_uri("/").rstrip("/") if request else "https://oentbox.com"
    movie_id = quote(str(movie.get("id", "")), safe="")
    items = [
        {
            "@type": "ListItem",
            "position": 1,
            "name": "Home",
            "item": base + "/",
        },
    ]
    if category:
        items.append({
            "@type": "ListItem",
            "position": 2,
            "name": category.replace("-", " ").title(),
            "item": base + "/browse.html?cat=" + category,
        })
        items.append({
            "@type": "ListItem",
            "position": 3,
            "name": str(movie.get("title", "")),
            "item": base + _clean_url(movie_id),
        })
    else:
        items.append({
            "@type": "ListItem",
            "position": 2,
            "name": str(movie.get("title", "")),
            "item": base + _clean_url(movie_id),
        })
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": items,
    }


def build_collection_page_schema(category_label, category_slug, total_movies, request=None):
    """schema.org CollectionPage data for browse pages."""
    base = request.build_absolute_uri("/").rstrip("/") if request else "https://oentbox.com"
    url = base + "/browse.html?cat=" + category_slug if category_slug != "all" else base + "/browse.html?cat=all"
    schema = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": category_label,
        "description": "Browse " + category_label + " on oentbox. Stream and discover Nollywood, Hollywood, Bollywood, K-drama, and world series.",
        "url": url,
    }
    if total_movies:
        schema["about"] = {
            "@type": "ItemList",
            "numberOfItems": total_movies,
        }
    return schema
