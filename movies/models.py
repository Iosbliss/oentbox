"""Movie models — designed around the data we scraped from 9jarocks.net."""
import re
from django.db import models
from django.utils.text import slugify
from django.utils import timezone


class Category(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    description = models.TextField(blank=True, default="")
    icon = models.CharField(max_length=40, blank=True, default="")  # emoji or icon name
    order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Genre(models.Model):
    name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=60, unique=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Movie(models.Model):
    title = models.CharField(max_length=250)
    slug = models.SlugField(max_length=300, unique=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True, related_name="movies")
    genres = models.ManyToManyField(Genre, blank=True, related_name="movies")
    poster_url = models.URLField(max_length=600, blank=True, default="")
    backdrop_url = models.URLField(max_length=600, blank=True, default="")
    plot = models.TextField(blank=True, default="")
    year = models.PositiveIntegerField(null=True, blank=True)
    country = models.CharField(max_length=100, blank=True, default="")
    language = models.CharField(max_length=80, blank=True, default="")
    movie_type = models.CharField(max_length=40, blank=True, default="Movie")  # Movie / TV Series / Anime / Wrestling
    duration = models.CharField(max_length=40, blank=True, default="")  # "120 min" or "10 episodes"
    imdb_url = models.URLField(blank=True, default="")
    trailer_url = models.URLField(max_length=600, blank=True, default="")  # YouTube embed URL
    source_url = models.URLField(max_length=600, blank=True, default="")
    rating = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    quality = models.CharField(max_length=30, blank=True, default="HD")
    status = models.CharField(max_length=40, blank=True, default="Released")  # Released / Ongoing / Complete
    is_featured = models.BooleanField(default=False)
    is_trending = models.BooleanField(default=False)
    is_new_release = models.BooleanField(default=False)
    views = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_trending"], name="movies_movi_is_tren_2aaa84_idx"),
            models.Index(fields=["is_new_release"], name="movies_movi_is_new__4458de_idx"),
            models.Index(fields=["is_featured"], name="movies_movi_is_feat_b67c49_idx"),
            models.Index(fields=["category"], name="movies_movi_categor_3d8279_idx"),
            models.Index(fields=["created_at"], name="movies_movi_created_36c764_idx"),
            models.Index(fields=["views"], name="movies_movi_views_8e3043_idx"),
            models.Index(fields=["rating"], name="movies_movi_rating_872ab8_idx"),
            models.Index(fields=["year"], name="movies_movi_year_e90d32_idx"),
        ]

    def __str__(self):
        return f"{self.title} ({self.year or '—'})"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:250]
            slug = base
            n = 2
            while Movie.objects.filter(slug=slug).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def short_plot(self):
        if not self.plot:
            return ""
        return self.plot[:140] + ("…" if len(self.plot) > 140 else "")

    @property
    def type_label(self):
        """Display-friendly type label."""
        t = (self.movie_type or "Movie").lower()
        if "series" in t or "tv" in t:
            return "TV Series"
        if "anime" in t:
            return "Anime"
        if "wrestling" in t or "sport" in t:
            return "Sports"
        return "Movie"

    @property
    def year_label(self):
        return str(self.year) if self.year else ""

    @property
    def youtube_id(self):
        """Extract YouTube video ID from trailer_url."""
        if not self.trailer_url:
            return ""
        # Handle embed URLs: https://www.youtube.com/embed/VIDEO_ID
        m = re.search(r'youtube\.com/embed/([a-zA-Z0-9_-]{11})', self.trailer_url)
        if m:
            return m.group(1)
        # Handle watch URLs: https://www.youtube.com/watch?v=VIDEO_ID
        m = re.search(r'youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})', self.trailer_url)
        if m:
            return m.group(1)
        # Handle youtu.be/VIDEO_ID
        m = re.search(r'youtu\.be/([a-zA-Z0-9_-]{11})', self.trailer_url)
        if m:
            return m.group(1)
        return ""

    @property
    def has_real_downloads(self):
        """True if this movie has real file-host download links (not just synthetic placeholders)."""
        return any("loadedfiles.org" in dl.url or "obqj2.com" not in dl.url for dl in self.download_links.all())


class DownloadLink(models.Model):
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="download_links")
    label = models.CharField(max_length=120)  # "Download 720p", "Episode 1 (1080p)"
    url = models.URLField(max_length=600)
    quality = models.CharField(max_length=30, blank=True, default="")  # 480p/720p/1080p
    size = models.CharField(max_length=30, blank=True, default="")  # "350 MB"
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.movie.title} — {self.label}"


class EpisodeThumbnail(models.Model):
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="thumbnails")
    image_url = models.URLField(max_length=600)
    caption = models.CharField(max_length=200, blank=True, default="")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]


class WatchlistItem(models.Model):
    """Lightweight watchlist stored by session key (no auth required)."""
    session_key = models.CharField(max_length=80, db_index=True)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name="watchlist_items")
    added_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ("session_key", "movie")
        ordering = ["-added_at"]

    def __str__(self):
        return f"{self.session_key[:8]}… → {self.movie.title}"