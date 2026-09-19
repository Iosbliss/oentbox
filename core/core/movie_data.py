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
    'tv-series': 'hollywood-tv-series',
    'hollywood': 'hollywood-movie',
}


FOREIGN_MARKERS = (
    'bollywood', 'indian', 'hindi', 'tamil', 'telugu', 'bengali', 'marathi',
    'punjabi', 'pakistani', 'spanish', 'french', 'german', 'italian',
    'arabic', 'indonesian', 'malaysian', 'russian', 'vietnamese', 'portuguese',
)


def classify_movie_category(title, description='', category='', metadata=None):
    """Match 9jaRocks-style country/type groups from title and description."""
    text = f'{title} {description} {metadata or ""}'.lower()
    legacy = LEGACY_CATEGORY_ALIASES.get(category, category)
    for specific_category, keywords in CATEGORY_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return specific_category
    series = any(keyword in text for keyword in ('season', 'episode', 'series', 'tv series'))
    if any(keyword in text for keyword in ('nollywood', 'nigerian', 'ghana')):
        return 'nollywood-tv-series' if series else 'nollywood-movie'
    if legacy in {'nollywood-movie', 'nollywood-tv-series'}:
        return legacy
    if any(keyword in text for keyword in ('hollywood', 'american', 'usa', 'u.s.a')):
        return 'hollywood-tv-series' if series else 'hollywood-movie'
    if legacy in {'hollywood-movie', 'hollywood-tv-series'}:
        if any(marker in text for marker in FOREIGN_MARKERS):
            return 'other-foreign-series' if series else 'foreign-movie'
        return legacy
    return 'other-foreign-series' if series else 'foreign-movie'


def normalize_movie_category(movie):
    """Normalize old records into the same groups used by new scrapes."""
    movie['category'] = classify_movie_category(
        movie.get('title', ''), movie.get('description', ''), movie.get('category', ''),
        movie.get('video_info', ''),
    )
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

def get_movies_by_category(category, limit=None):
    """Get category results using a bounded database query."""
    queryset = Movie.objects.exclude(category__in=EXCLUDED_CATEGORIES).filter(category=category).values()
    return _movie_values(queryset[:limit] if limit else queryset)

def get_featured_movies(limit=6):
    """Get featured movies using the catalog ordering."""
    queryset = Movie.objects.exclude(category__in=EXCLUDED_CATEGORIES).values()[:limit]
    return _movie_values(queryset)

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
