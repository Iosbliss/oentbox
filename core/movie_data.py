import json
import os
from django.conf import settings
from django.core.cache import cache
from .models import Movie

MOVIES_FILE = os.path.join(settings.BASE_DIR, 'scraper', 'movies.json')
# Categories that should never appear on the public website. Sport content
# (sport-live, sport, sports, wrestling) was removed per product requirement;
# the set is kept as a defensive filter so the catalog cannot be re-polluted
# by legacy data or by a future scraper run.
EXCLUDED_CATEGORIES = {'sport-live', 'sport', 'sports', 'wrestling', 'wrestling-live'}

CATEGORY_LABELS = {
    'nollywood-movie': 'Nollywood Movies',
    'nollywood-tv-series': 'Nollywood Series',
    'hollywood-movie': 'Hollywood Movies',
    'hollywood-tv-series': 'Hollywood Series',
    'bollywood-movie': 'Bollywood Movies',
    'bollywood-tv-series': 'Bollywood Series',
    'foreign-movie': 'Foreign Movies',
    'other-foreign-series': 'Other Foreign Series',
    'korean-drama': 'Korean Drama',
    'chinese-drama': 'Chinese Drama',
    'japanese-drama': 'Japanese Drama',
    'filipino-drama': 'Filipino Drama',
    'turkish-drama': 'Turkish Drama',
    'thai-drama': 'Thai Drama',
    'anime': 'Anime',
}

CATEGORY_KEYWORDS = (
    ('anime', ('anime', 'cartoon', 'animation')),
    ('korean-drama', ('korean', 'k-drama', 'kdrama')),
    ('chinese-drama', ('chinese', 'c-drama', 'cdrama')),
    ('japanese-drama', ('japanese', 'j-drama', 'jdrama')),
    ('filipino-drama', ('filipino', 'philippines')),
    ('turkish-drama', ('turkish', 'turkey')),
    ('thai-drama', ('thai', 'thailand')),
)

LEGACY_CATEGORY_ALIASES = {
    'nollywood': 'nollywood-movie',
    'nollywood-series': 'nollywood-tv-series',
    'nollywood-movies': 'nollywood-movie',
    'nollywood-movie': 'nollywood-movie',
    'nollywood-tv-series': 'nollywood-tv-series',
    'tv-series': 'hollywood-tv-series',
    'hollywood': 'hollywood-movie',
    'hollywood-movies': 'hollywood-movie',
    'hollywood-series': 'hollywood-tv-series',
    'hollywood-movie': 'hollywood-movie',
    'hollywood-tv-series': 'hollywood-tv-series',
    'bollywood-movies': 'bollywood-movie',
    'bollywood-series': 'bollywood-tv-series',
    'bollywood-movie': 'bollywood-movie',
    'foreign-series': 'other-foreign-series',
}


FOREIGN_MARKERS = (
    'bollywood', 'indian', 'hindi', 'tamil', 'telugu', 'bengali', 'marathi',
    'punjabi', 'pakistani', 'spanish', 'french', 'german', 'italian',
    'arabic', 'indonesian', 'malaysian', 'russian', 'vietnamese', 'portuguese',
)

NIGERIAN_TITLE_MARKERS = ('wura',)
NIGERIAN_PRODUCTION_MARKERS = (
    'nollywood', 'naija', 'bbnaija', 'big brother naija',
    'nigerian movie', 'nigerian series', 'nigerian film', 'nigerian drama',
)


def classify_movie_category(title, description='', category='', metadata=None):
    """Match 9jaRocks-style country/type groups from title and description."""
    text = f'{title} {description} {metadata or ""}'.lower()
    metadata_country = str(metadata.get('Country', '') if isinstance(metadata, dict) else '').lower()
    legacy = LEGACY_CATEGORY_ALIASES.get(category, category)
    if legacy in {'nollywood-movie', 'nollywood-tv-series', 'nollywood-series'}:
        return legacy
    if legacy in {'bollywood-movie', 'bollywood-tv-series', 'bollywood-series'}:
        return legacy
    if legacy in {'hollywood-movie', 'hollywood-tv-series', 'hollywood-series'}:
        if any(marker in text for marker in FOREIGN_MARKERS):
            return 'other-foreign-series' if any(keyword in text for keyword in ('season', 'episode', 'series', 'tv series')) else 'foreign-movie'
        return legacy
    for specific_category, keywords in CATEGORY_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return specific_category
    series = any(keyword in text for keyword in ('season', 'episode', 'series', 'tv series'))
    if 'bollywood' in text:
        return 'bollywood-tv-series' if series else 'bollywood-movie'
    title_text = str(title or '').lower()
    if 'nigeria' in metadata_country or any(marker in text for marker in NIGERIAN_PRODUCTION_MARKERS) or any(
        marker in title_text for marker in NIGERIAN_TITLE_MARKERS
    ) or any(marker in title_text for marker in ('nigerian', 'ghanaian')):
        return 'nollywood-tv-series' if series else 'nollywood-movie'
    if any(marker in text for marker in FOREIGN_MARKERS):
        return 'other-foreign-series' if series else 'foreign-movie'
    if any(keyword in text for keyword in ('hollywood', 'american', 'usa', 'u.s.a')):
        return 'hollywood-tv-series' if series else 'hollywood-movie'
    return 'other-foreign-series' if series else 'foreign-movie'


def normalize_movie_category(movie):
    """Normalize only known legacy labels without reclassifying stored records.

    Category inference belongs to the scraper. Re-running it while rendering
    pages makes the same record appear in different categories depending on
    which view loaded it, and can misclassify titles from incidental words in
    their descriptions or metadata.
    """
    category = movie.get('category', '')
    movie['category'] = LEGACY_CATEGORY_ALIASES.get(category, category)
    return movie

def load_movies():
    """Load the catalog from the database, with JSON as a legacy fallback."""
    movies = list(Movie.objects.exclude(category__in=EXCLUDED_CATEGORIES).values())
    if movies:
        for movie in movies:
            movie['scraped_at'] = movie['scraped_at'].strftime('%Y-%m-%d %H:%M:%S')
        return [normalize_movie_category(movie) for movie in movies if movie.get('category') not in EXCLUDED_CATEGORIES]
    try:
        if os.path.exists(MOVIES_FILE):
            with open(MOVIES_FILE, 'r', encoding='utf-8') as f:
                return [normalize_movie_category(movie) for movie in json.load(f) if movie.get('category') not in EXCLUDED_CATEGORIES]
        return []
    except Exception as e:
        print(f"Error loading movies: {e}")
        return []

# Category rows are identical for every visitor, so the result is cached in the
# shared cache backend (Redis in production). The home page alone renders ~16
# category rows, which previously meant ~16 uncached queries per request.
CATALOG_CACHE_TTL = int(os.environ.get('CATALOG_CACHE_TTL', '300'))


def count_movies():
    """Number of catalog titles, cached.

    The about page only needs the total, so a single COUNT replaces loading
    every row (22k+ titles) into Python just to take its length.
    """
    cached = cache.get('catalog:count')
    if cached is not None:
        return cached
    if Movie.objects.exists():
        total = Movie.objects.exclude(category__in=EXCLUDED_CATEGORIES).count()
    else:
        total = len(load_movies())
    cache.set('catalog:count', total, CATALOG_CACHE_TTL)
    return total


def _cached_movie_values(cache_key, queryset, limit=None):
    """Return picklable movie dicts from the cache, filling it on a miss."""
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    values = _movie_values(queryset[:limit] if limit else queryset)
    cache.set(cache_key, values, CATALOG_CACHE_TTL)
    return values


def get_movies_by_category(category, limit=None):
    """Get category results using a bounded, cached database query."""
    category = LEGACY_CATEGORY_ALIASES.get(category, category)
    database_categories = [category]
    database_categories.extend(
        legacy for legacy, normalized in LEGACY_CATEGORY_ALIASES.items()
        if normalized == category
    )
    queryset = (Movie.objects.exclude(category__in=EXCLUDED_CATEGORIES)
                .filter(category__in=database_categories).values())
    return _cached_movie_values(f'catalog:category:{category}:{limit or 0}', queryset, limit)

def get_featured_movies(limit=6):
    """Get featured movies using the cached catalog ordering."""
    queryset = Movie.objects.exclude(category__in=EXCLUDED_CATEGORIES).values()
    return _cached_movie_values(f'catalog:featured:{limit}', queryset, limit)

def get_movie_by_id(movie_id):
    """Get one movie without loading the full catalog."""
    movie = Movie.objects.exclude(category__in=EXCLUDED_CATEGORIES).filter(id=movie_id).values().first()
    return _normalize_movie_value(movie) if movie else None

def get_categories():
    cached = cache.get('catalog:categories')
    if cached is not None:
        return cached
    categories = list(
        Movie.objects.exclude(category__in=EXCLUDED_CATEGORIES)
        .values_list('category', flat=True).distinct().order_by('category')
    )
    categories = sorted({LEGACY_CATEGORY_ALIASES.get(category, category) for category in categories})
    cache.set('catalog:categories', categories, 300)
    return categories

def search_movies(query, limit=20):
    from django.db.models import Q

    queryset = (Movie.objects.exclude(category__in=EXCLUDED_CATEGORIES)
                .filter(Q(title__icontains=query) | Q(description__icontains=query))
                .values()[:limit])
    return _movie_values(queryset)


def _normalize_movie_value(movie):
    if movie and movie.get('scraped_at'):
        movie['scraped_at'] = movie['scraped_at'].strftime('%Y-%m-%d %H:%M:%S')
    return normalize_movie_category(movie)


def _movie_values(queryset):
    return [_normalize_movie_value(movie) for movie in queryset]
