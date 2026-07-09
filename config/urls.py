"""Project URL configuration."""
from django.contrib import admin
from django.urls import path
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static
from movies import views

urlpatterns = [
    path("admin/", admin.site.urls),

    # PWA
    path("manifest.json", views.manifest, name="manifest"),
    path("sw.js", views.service_worker, name="service_worker"),
    path("offline/", views.offline, name="offline"),

    # Main pages
    path("", views.home, name="home"),
    path("browse/", views.browse, name="browse"),
    path("search/", views.search, name="search"),
    path("watchlist/", views.watchlist, name="watchlist"),
    path("category/<slug:slug>/", views.category_view, name="category"),
    path("movie/<slug:slug>/", views.movie_detail, name="movie_detail"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    # HTMX endpoints
    path("movies/row/<slug:slug>/", views.row_partial, name="row_partial"),
    path("movies/watchlist/<int:movie_id>/", views.toggle_watchlist, name="toggle_watchlist"),
    path("movies/suggestions/", views.suggestions, name="suggestions"),

    # Favicon
    path("favicon.ico", RedirectView.as_view(url="/static/pwa/favicon.ico", permanent=True)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
