"""Views — full pages + HTMX partials for infinite scroll, search, watchlist."""
import json
import random
from django.shortcuts import get_object_or_404, render, redirect
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.csrf import csrf_protect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.core.paginator import Paginator
from django.db.models import Q, Count
from .models import Category, Genre, Movie, WatchlistItem, DownloadLink, EpisodeThumbnail


def get_session_key(request):
    """Get or create a stable session key for the visitor."""
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def is_htmx(request):
    return request.headers.get("HX-Request") == "true"


# --------------------------------------------------------------------
# Full pages
# --------------------------------------------------------------------

def home(request):
    """Splash-style home with hero, rows of content (Netflix / app-style)."""
    featured = Movie.objects.filter(is_featured=True).select_related("category")[:6]
    # If not enough featured, top up with recent
    if featured.count() < 5:
        featured = Movie.objects.order_by("-created_at")[:6]

    hero = featured.first() if featured else None

    rows = [
        {
            "title": "🔥 Trending Now",
            "slug": "trending",
            "movies": list(Movie.objects.filter(is_trending=True).select_related('category').order_by("-views")[:14]),
            "endpoint": "/movies/row/trending/",
        },
        {
            "title": "🆕 New Releases",
            "slug": "new",
            "movies": list(Movie.objects.filter(is_new_release=True).select_related('category').order_by("-created_at")[:14]),
            "endpoint": "/movies/row/new/",
        },
        {
            "title": "🎬 Nollywood Picks",
            "slug": "nollywood",
            "movies": list(Movie.objects.filter(category__slug__in=["nollywood", "nollywood-series"]).select_related("category").order_by("-created_at")[:14]),
            "endpoint": "/movies/row/nollywood/",
        },
        {
            "title": "🍿 Hollywood Blockbusters",
            "slug": "hollywood",
            "movies": list(Movie.objects.filter(category__slug__in=["hollywood", "hollywood-series"]).select_related("category").order_by("-created_at")[:14]),
            "endpoint": "/movies/row/hollywood/",
        },
        {
            "title": "🇰🇷 Korean Drama",
            "slug": "korean-drama",
            "movies": list(Movie.objects.filter(category__slug="korean-drama").order_by("-created_at")[:14]),
            "endpoint": "/movies/row/korean-drama/",
        },
        {
            "title": "🇨🇳 Chinese Drama",
            "slug": "chinese-drama",
            "movies": list(Movie.objects.filter(category__slug="chinese-drama").order_by("-created_at")[:14]),
            "endpoint": "/movies/row/chinese-drama/",
        },
        {
            "title": "🇹🇭 Thai Drama",
            "slug": "thai-drama",
            "movies": list(Movie.objects.filter(category__slug="thai-drama").order_by("-created_at")[:14]),
            "endpoint": "/movies/row/thai-drama/",
        },
        {
            "title": "🇵🇭 Filipino Drama",
            "slug": "filipino-drama",
            "movies": list(Movie.objects.filter(category__slug="filipino-drama").order_by("-created_at")[:14]),
            "endpoint": "/movies/row/filipino-drama/",
        },
        {
            "title": "🇯🇵 Japanese Drama",
            "slug": "japanese-drama",
            "movies": list(Movie.objects.filter(category__slug="japanese-drama").order_by("-created_at")[:14]),
            "endpoint": "/movies/row/japanese-drama/",
        },
        {
            "title": "🌸 Anime",
            "slug": "anime",
            "movies": list(Movie.objects.filter(category__slug="anime").order_by("-created_at")[:14]),
            "endpoint": "/movies/row/anime/",
        },
        {
            "title": "🌍 Foreign Gems",
            "slug": "foreign",
            "movies": list(Movie.objects.filter(category__slug="foreign").order_by("-created_at")[:14]),
            "endpoint": "/movies/row/foreign/",
        },
        {
            "title": "🌠 Other Foreign Series",
            "slug": "other-foreign-series",
            "movies": list(Movie.objects.filter(category__slug="other-foreign-series").order_by("-created_at")[:14]),
            "endpoint": "/movies/row/other-foreign-series/",
        },
        {
            "title": "🤼 Pro Wrestling",
            "slug": "wrestling",
            "movies": list(Movie.objects.filter(category__slug="wrestling").order_by("-created_at")[:14]),
            "endpoint": "/movies/row/wrestling/",
        },
    ]

    # Filter out empty rows
    rows = [r for r in rows if r["movies"]]

    # Bottom hero card pool (5)
    hero_pool = list(featured[:5])

    context = {
        "hero": hero,
        "hero_pool": hero_pool,
        "rows": rows,
        "page_title": "Home",
    }
    return render(request, "movies/home.html", context)


def browse(request):
    """All movies grid with filters + infinite scroll."""
    movies = Movie.objects.select_related("category").all()

    cat = request.GET.get("cat")
    genre = request.GET.get("genre")
    q = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", "new")

    if cat:
        movies = movies.filter(category__slug=cat)
    if genre:
        movies = movies.filter(genres__slug=genre)
    if q:
        movies = movies.filter(Q(title__icontains=q) | Q(plot__icontains=q) | Q(country__icontains=q))

    if sort == "rating":
        movies = movies.order_by("-rating")
    elif sort == "views":
        movies = movies.order_by("-views")
    elif sort == "title":
        movies = movies.order_by("title")
    else:
        movies = movies.order_by("-created_at")

    page = int(request.GET.get("page", 1))
    paginator = Paginator(movies, 24)
    page_obj = paginator.get_page(page)

    all_genres = Genre.objects.annotate(movie_count=Count("movies")).filter(movie_count__gt=0).order_by("-movie_count")

    context = {
        "movies": page_obj.object_list,
        "page_obj": page_obj,
        "categories": Category.objects.filter(is_active=True).order_by("order", "name"),
        "genres": all_genres,
        "current_cat": cat or "",
        "current_genre": genre or "",
        "current_q": q,
        "current_sort": sort,
        "page_title": "Browse",
    }

    if is_htmx(request):
        # Return just the grid partial for infinite scroll
        return render(request, "movies/partials/_movie_grid_page.html", context)
    return render(request, "movies/browse.html", context)


def movie_detail(request, slug):
    movie = get_object_or_404(Movie.objects.select_related('category'), slug=slug)
    # Increment views
    Movie.objects.filter(pk=movie.pk).update(views=movie.views + 1)
    movie.refresh_from_db()

    # Related: same category, exclude self
    related = (
        Movie.objects.filter(category=movie.category)
        .exclude(pk=movie.pk)
        .select_related('category')
        .order_by("-created_at")[:8]
    )
    # If not enough, fill from same genre or any
    if related.count() < 6:
        more = Movie.objects.exclude(pk=movie.pk).exclude(pk__in=[m.pk for m in related]).order_by("-views")[: 8 - related.count()]
        related = list(related) + list(more)

    # Watchlist state
    session_key = get_session_key(request)
    in_watchlist = WatchlistItem.objects.filter(session_key=session_key, movie=movie).exists()

    # Recommended: random 5 from same category or any
    rec_pool = list(Movie.objects.exclude(pk=movie.pk).order_by("?")[:5])

    context = {
        "movie": movie,
        "related": related,
        "recommended": rec_pool,
        "in_watchlist": in_watchlist,
        "page_title": movie.title,
    }
    return render(request, "movies/detail.html", context)


def category_view(request, slug):
    """Category landing page."""
    cat = get_object_or_404(Category, slug=slug, is_active=True)
    movies = Movie.objects.filter(category=cat).select_related('category').order_by("-created_at")
    page = int(request.GET.get("page", 1))
    paginator = Paginator(movies, 24)
    page_obj = paginator.get_page(page)

    context = {
        "category": cat,
        "movies": page_obj.object_list,
        "page_obj": page_obj,
        "page_title": cat.name,
    }
    if is_htmx(request):
        return render(request, "movies/partials/_movie_grid_page.html", context)
    return render(request, "movies/category.html", context)


def search(request):
    """Search results — supports HTMX live results."""
    q = request.GET.get("q", "").strip()
    movies = Movie.objects.none()
    if q:
        movies = Movie.objects.filter(
            Q(title__icontains=q) | Q(plot__icontains=q) | Q(country__icontains=q) | Q(genres__name__icontains=q)
        ).distinct().select_related('category').order_by("-views")[:30]

    context = {"movies": movies, "q": q, "page_title": f"Search: {q}"}
    if is_htmx(request):
        return render(request, "movies/partials/_search_results.html", context)
    return render(request, "movies/search.html", context)


def watchlist(request):
    """User's saved movies (per session)."""
    session_key = get_session_key(request)
    items = WatchlistItem.objects.filter(session_key=session_key).select_related("movie", "movie__category").order_by("-added_at")
    movies = [item.movie for item in items]
    context = {"movies": movies, "page_title": "My List"}
    return render(request, "movies/watchlist.html", context)


# --------------------------------------------------------------------
# HTMX endpoints
# --------------------------------------------------------------------

ROW_BUILDERS = {
    "trending": lambda: Movie.objects.filter(is_trending=True).select_related("category").order_by("-views"),
    "new": lambda: Movie.objects.filter(is_new_release=True).select_related("category").order_by("-created_at"),
    "nollywood": lambda: Movie.objects.filter(category__slug__in=["nollywood", "nollywood-series"]).select_related("category").order_by("-created_at"),
    "hollywood": lambda: Movie.objects.filter(category__slug__in=["hollywood", "hollywood-series"]).select_related("category").order_by("-created_at"),
    "korean-drama": lambda: Movie.objects.filter(category__slug="korean-drama").select_related("category").order_by("-created_at"),
    "chinese-drama": lambda: Movie.objects.filter(category__slug="chinese-drama").select_related("category").order_by("-created_at"),
    "thai-drama": lambda: Movie.objects.filter(category__slug="thai-drama").select_related("category").order_by("-created_at"),
    "filipino-drama": lambda: Movie.objects.filter(category__slug="filipino-drama").select_related("category").order_by("-created_at"),
    "japanese-drama": lambda: Movie.objects.filter(category__slug="japanese-drama").select_related("category").order_by("-created_at"),
    "anime": lambda: Movie.objects.filter(category__slug="anime").select_related("category").order_by("-created_at"),
    "foreign": lambda: Movie.objects.filter(category__slug="foreign").select_related("category").order_by("-created_at"),
    "other-foreign-series": lambda: Movie.objects.filter(category__slug="other-foreign-series").select_related("category").order_by("-created_at"),
    "wrestling": lambda: Movie.objects.filter(category__slug="wrestling").select_related("category").order_by("-created_at"),
}


@require_GET
def row_partial(request, slug):
    """Return additional movies for a home row (paginated, for infinite scroll within row)."""
    builder = ROW_BUILDERS.get(slug)
    if not builder:
        return HttpResponse("", status=404)
    offset = int(request.GET.get("offset", 14))
    qs = builder()[offset : offset + 14]
    context = {"movies": list(qs), "row_slug": slug, "next_offset": offset + 14}
    return render(request, "movies/partials/_row_cards.html", context)


@require_POST
@csrf_protect
def toggle_watchlist(request, movie_id):
    """Add/remove from watchlist, returns updated button."""
    movie = get_object_or_404(Movie, pk=movie_id)
    session_key = get_session_key(request)
    item, created = WatchlistItem.objects.get_or_create(session_key=session_key, movie=movie)
    if not created:
        item.delete()
        in_list = False
    else:
        in_list = True
    context = {"movie": movie, "in_watchlist": in_list}
    return render(request, "movies/partials/_watchlist_button.html", context)


@require_GET
def suggestions(request):
    """Live search suggestions for the top search bar."""
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return HttpResponse("")
    movies = Movie.objects.filter(title__icontains=q).select_related('category').order_by("-views")[:6]
    context = {"movies": movies, "q": q}
    return render(request, "movies/partials/_suggestions.html", context)


def offline(request):
    """PWA offline fallback page."""
    return render(request, "movies/offline.html", {})


def login_view(request):
    """Admin login page."""
    if request.user.is_authenticated:
        return redirect('dashboard')
    error = ''
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is not None and user.is_staff:
            login(request, user)
            return redirect('dashboard')
        elif user is not None and not user.is_staff:
            error = 'This account does not have admin access.'
        else:
            error = 'Invalid username or password.'
    return render(request, 'movies/login.html', {'error': error, 'page_title': 'Admin Login'})


def logout_view(request):
    """Logout and redirect to home."""
    logout(request)
    return redirect('home')


@login_required(login_url='/login/')
def dashboard(request):
    """Advanced admin dashboard showing comprehensive site statistics.
    Only accessible to logged-in staff/admin users."""
    from django.db.models import Sum, Avg, Count, Q
    from django.utils import timezone
    from datetime import timedelta

    # ---- Core stats ----
    total_movies = Movie.objects.count()
    total_categories = Category.objects.count()
    total_genres = Genre.objects.count()
    total_download_links = DownloadLink.objects.count()
    total_thumbnails = EpisodeThumbnail.objects.count()
    total_watchlist_items = WatchlistItem.objects.count()

    # ---- Movie quality stats ----
    movies_with_trailer = Movie.objects.exclude(trailer_url="").count()
    movies_with_poster = Movie.objects.exclude(poster_url="").count()
    movies_with_plot = Movie.objects.exclude(plot="").count()
    movies_with_downloads = Movie.objects.filter(download_links__isnull=False).distinct().count()

    # ---- Views stats ----
    total_views = Movie.objects.aggregate(total=Sum("views"))["total"] or 0
    avg_rating = Movie.objects.aggregate(avg=Avg("rating"))["avg"] or 0
    avg_views = total_views / total_movies if total_movies > 0 else 0

    # ---- Top movies by views ----
    top_movies_views = list(Movie.objects.order_by("-views")[:10].values("title", "views", "rating", "category__name"))

    # ---- Top movies by rating ----
    top_movies_rating = list(Movie.objects.order_by("-rating")[:10].values("title", "rating", "views", "category__name"))

    # ---- Movies per category (for bar chart) ----
    category_stats = []
    for c in Category.objects.all().order_by("order"):
        count = Movie.objects.filter(category=c).count()
        views = Movie.objects.filter(category=c).aggregate(v=Sum("views"))["v"] or 0
        downloads = DownloadLink.objects.filter(movie__category=c).count()
        category_stats.append({
            "name": c.name,
            "icon": c.icon,
            "slug": c.slug,
            "movie_count": count,
            "total_views": views,
            "download_links": downloads,
        })

    # ---- Top genres ----
    top_genres = list(
        Genre.objects.annotate(movie_count=Count("movies"))
        .filter(movie_count__gt=0)
        .order_by("-movie_count")[:15]
        .values("name", "movie_count")
    )

    # ---- Status distribution ----
    status_counts = {}
    for status_choice in ["Released", "Ongoing", "Complete"]:
        count = Movie.objects.filter(status=status_choice).count()
        status_counts[status_choice] = count

    # ---- Type distribution ----
    type_counts = {}
    for m in Movie.objects.all():
        t = m.type_label
        type_counts[t] = type_counts.get(t, 0) + 1

    # ---- Year distribution (for chart) ----
    year_stats = {}
    for m in Movie.objects.exclude(year__isnull=True).values("year"):
        y = m["year"]
        if y:
            decade = (y // 10) * 10
            year_stats[decade] = year_stats.get(decade, 0) + 1
    year_data = sorted(year_stats.items())

    # ---- Recent movies (last 7 days) ----
    seven_days_ago = timezone.now() - timedelta(days=7)
    recent_movies = list(
        Movie.objects.filter(created_at__gte=seven_days_ago)
        .order_by("-created_at")[:10]
        .values("title", "category__name", "created_at", "views")
    )

    # ---- Country distribution (top 10) ----
    country_stats = {}
    for m in Movie.objects.exclude(country=""):
        for country in m.country.split(","):
            country = country.strip()
            if country:
                country_stats[country] = country_stats.get(country, 0) + 1
    top_countries = sorted(country_stats.items(), key=lambda x: -x[1])[:10]

    # ---- Download links per quality ----
    quality_stats = {}
    for dl in DownloadLink.objects.exclude(quality=""):
        q = dl.quality
        quality_stats[q] = quality_stats.get(q, 0) + 1
    quality_data = sorted(quality_stats.items(), key=lambda x: -x[1])

    # ---- Calculate percentages for progress bars ----
    trailer_pct = (movies_with_trailer * 100 / total_movies) if total_movies > 0 else 0
    poster_pct = (movies_with_poster * 100 / total_movies) if total_movies > 0 else 0
    plot_pct = (movies_with_plot * 100 / total_movies) if total_movies > 0 else 0
    downloads_pct = (movies_with_downloads * 100 / total_movies) if total_movies > 0 else 0

    context = {
        "page_title": "Dashboard",
        # Core stats
        "total_movies": total_movies,
        "total_categories": total_categories,
        "total_genres": total_genres,
        "total_download_links": total_download_links,
        "total_thumbnails": total_thumbnails,
        "total_watchlist_items": total_watchlist_items,
        # Quality stats
        "movies_with_trailer": movies_with_trailer,
        "movies_with_poster": movies_with_poster,
        "movies_with_plot": movies_with_plot,
        "movies_with_downloads": movies_with_downloads,
        "trailer_pct": round(trailer_pct, 1),
        "poster_pct": round(poster_pct, 1),
        "plot_pct": round(plot_pct, 1),
        "downloads_pct": round(downloads_pct, 1),
        # Views stats
        "total_views": total_views,
        "avg_rating": round(avg_rating, 1) if avg_rating else 0,
        "avg_views": int(avg_views),
        # Charts
        "category_stats": category_stats,
        "top_genres": top_genres,
        "status_counts": status_counts,
        "type_counts": type_counts,
        "year_data": year_data,
        "top_countries": top_countries,
        "quality_data": quality_data,
        # Tables
        "top_movies_views": top_movies_views,
        "top_movies_rating": top_movies_rating,
        "recent_movies": recent_movies,
    }
    return render(request, "movies/dashboard.html", context)


def manifest(request):
    """PWA manifest.json"""
    data = {
        "name": "OentBox — Stream & Download",
        "short_name": "OentBox",
        "description": "Stream and download Nollywood, Hollywood, K-Drama, Anime and more.",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0a0a0f",
        "theme_color": "#0a0a0f",
        "orientation": "portrait-primary",
        "categories": ["entertainment", "video"],
        "icons": [
            {"src": "/static/pwa/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/static/pwa/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
        "shortcuts": [
            {"name": "Browse", "url": "/browse/", "short_name": "Browse"},
            {"name": "Search", "url": "/search/", "short_name": "Search"},
            {"name": "My List", "url": "/watchlist/", "short_name": "My List"},
        ],
    }
    return JsonResponse(data, json_dumps_params={"indent": 2})


def service_worker(request):
    sw_js = '''
var CACHE = "oentbox-v2";
var STATIC = "/static/";

self.addEventListener("install", function(e) {
  e.waitUntil(
    caches.open(CACHE).then(function(c) {
      return c.addAll(["/", "/offline/", "/static/movies/css/app.css?v=6", "/static/movies/js/app.js?v=4", "/static/movies/js/htmx.min.js"]);
    }).then(function() { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function(e) {
  e.waitUntil(
    caches.keys().then(function(ks) {
      return Promise.all(ks.map(function(k) { if (k !== CACHE) return caches.delete(k); }));
    }).then(function() { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function(e) {
  var u = new URL(e.request.url);
  if (u.pathname.startsWith(STATIC)) {
    e.respondWith(caches.match(e.request).then(function(r) { return r || fetch(e.request).then(function(r2) { var c = r2.clone(); caches.open(CACHE).then(function(ca) { ca.put(e.request, c); }); return r2; }); }));
    return;
  }
  if (e.request.mode === "navigate") {
    e.respondWith(fetch(e.request).then(function(r) { var c = r.clone(); caches.open(CACHE).then(function(ca) { ca.put(e.request, c); }); return r; }).catch(function() { return caches.match(e.request).then(function(r) { return r || caches.match("/offline/"); }); }));
    return;
  }
  e.respondWith(fetch(e.request));
});
'''.strip()
    return HttpResponse(sw_js, content_type="application/javascript")


def not_found(request, exception=None):
    return render(request, "movies/404.html", {"page_title": "404"}, status=404)

def server_error(request):
    return render(request, "movies/500.html", {"page_title": "500"}, status=500)

def sitemap(request):
    """XML sitemap for better SEO indexing."""
    from django.template.loader import render_to_string
    from django.urls import reverse

    pages = [
        (reverse('home'), '1.0', 'daily'),
        (reverse('browse'), '0.9', 'weekly'),
        (reverse('watchlist'), '0.5', 'weekly'),
        (reverse('search'), '0.5', 'weekly'),
    ]

    categories = Category.objects.filter(is_active=True)
    for cat in categories:
        pages.append((reverse('category', args=[cat.slug]), '0.7', 'weekly'))

    movies = Movie.objects.all().only('slug', 'updated_at')
    urls = []
    for m in movies:
        urls.append({
            'loc': request.build_absolute_uri(reverse('movie_detail', args=[m.slug])),
            'lastmod': m.updated_at.strftime('%Y-%m-%d') if m.updated_at else '',
            'changefreq': 'monthly',
            'priority': '0.5',
        })

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for url, priority, changefreq in pages:
        loc = request.build_absolute_uri(url)
        xml += f'  <url>\n    <loc>{loc}</loc>\n    <changefreq>{changefreq}</changefreq>\n    <priority>{priority}</priority>\n  </url>\n'
    for u in urls:
        xml += '  <url>\n    <loc>' + u['loc'] + '</loc>\n'
        if u['lastmod']:
            xml += '    <lastmod>' + u['lastmod'] + '</lastmod>\n'
        xml += '    <changefreq>' + u['changefreq'] + '</changefreq>\n'
        xml += '    <priority>' + u['priority'] + '</priority>\n  </url>\n'
    xml += '</urlset>'
    return HttpResponse(xml, content_type='application/xml')


def robots_txt(request):
    """robots.txt for crawler guidance."""
    lines = [
        'User-agent: *',
        'Allow: /',
        'Disallow: /admin/',
        'Disallow: /login/',
        'Disallow: /dashboard/',
        '',
        'Sitemap: ' + request.build_absolute_uri('/sitemap.xml'),
    ]
    return HttpResponse('\n'.join(lines), content_type='text/plain')
