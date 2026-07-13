from django.contrib import admin
from .models import Category, Genre, Movie, DownloadLink, EpisodeThumbnail, WatchlistItem

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ("name",)}
    list_display = ("name", "order", "is_active")
    list_editable = ("order", "is_active")
    search_fields = ("name",)

@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ("name",)}
    list_display = ("name",)
    search_fields = ("name",)

class DownloadLinkInline(admin.TabularInline):
    model = DownloadLink
    extra = 1
    fields = ("label", "url", "quality", "size", "order")

class EpisodeThumbnailInline(admin.TabularInline):
    model = EpisodeThumbnail
    extra = 0
    fields = ("image_url", "caption", "order")

@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ("title",)}
    list_display = ("title", "category", "year", "rating", "views", "is_featured", "is_trending", "is_new_release", "created_at")
    list_editable = ("is_featured", "is_trending", "is_new_release")
    list_filter = ("category", "is_featured", "is_trending", "is_new_release", "status", "movie_type", "year")
    search_fields = ("title", "plot", "country")
    inlines = [DownloadLinkInline, EpisodeThumbnailInline]
    readonly_fields = ("views", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("title", "slug", "category", "genres")}),
        ("Details", {"fields": ("plot", "year", "country", "language", "movie_type", "duration", "status", "rating", "quality")}),
        ("Media", {"fields": ("poster_url", "backdrop_url", "trailer_url", "imdb_url", "source_url")}),
        ("Flags", {"fields": ("is_featured", "is_trending", "is_new_release")}),
        ("Stats", {"fields": ("views", "created_at", "updated_at")}),
    )

@admin.register(WatchlistItem)
class WatchlistItemAdmin(admin.ModelAdmin):
    list_display = ("movie", "session_key", "added_at")
    search_fields = ("session_key", "movie__title")
    readonly_fields = ("added_at",)

admin.site.register(DownloadLink)
admin.site.register(EpisodeThumbnail)
