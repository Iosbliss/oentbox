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
STATIC_PATHS = ("/", "/about.html", "/browse.html?cat=all", "/youtube.html")


def _base_url(request):
    return request.build_absolute_uri("/").rstrip("/")


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
                '<url><loc>%s/video_detail.html?id=%s</loc>%s</url>'
                % (base, escape(quote(str(row["id"]), safe="")), lastmod)
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
        schema["url"] = request.build_absolute_uri()
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
    trailer = movie.get("trailer_embed_url") or movie.get("trailer_url")
    if trailer:
        schema["trailer"] = {"@type": "VideoObject", "url": trailer}
    return schema
