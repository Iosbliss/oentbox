from django.conf import settings
from django.db import models


class ActivityEvent(models.Model):
	DOWNLOAD = 'download'
	TRAILER_WATCH = 'trailer_watch'
	YOUTUBE_SEARCH = 'youtube_search'
	YOUTUBE_DOWNLOAD = 'youtube_download'
	EVENT_TYPES = (
		(DOWNLOAD, 'Download'),
		(TRAILER_WATCH, 'Trailer watch'),
		(YOUTUBE_SEARCH, 'YouTube search'),
		(YOUTUBE_DOWNLOAD, 'YouTube download'),
	)

	movie_id = models.CharField(max_length=255)
	movie_title = models.CharField(max_length=255, blank=True)
	event_type = models.CharField(max_length=30, choices=EVENT_TYPES)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ('-created_at',)


class Movie(models.Model):
	id = models.CharField(max_length=255, primary_key=True)
	title = models.CharField(max_length=500, db_index=True)
	description = models.TextField(blank=True)
	thumbnail = models.URLField(max_length=500, blank=True)
	link = models.URLField(max_length=500, unique=True)
	year = models.PositiveIntegerField(null=True, blank=True, db_index=True)
	category = models.CharField(max_length=100, db_index=True)
	source = models.CharField(max_length=100, default='9jarocks')
	scraped_at = models.DateTimeField(db_index=True)
	video_info = models.JSONField(default=dict, blank=True)
	trailer_url = models.URLField(max_length=500, blank=True)
	trailer_embed_url = models.URLField(max_length=500, blank=True)
	trailer_title = models.CharField(max_length=500, blank=True)
	download_links = models.JSONField(default=list, blank=True)
	download_help_url = models.CharField(max_length=500, blank=True)
	screenshots = models.JSONField(default=list, blank=True)

	class Meta:
		ordering = ('-scraped_at', 'title')
		indexes = [
			models.Index(fields=('category', 'scraped_at'), name='core_movie_categor_3a37e4_idx'),
			models.Index(fields=('title', 'year'), name='core_movie_title_4cf2dd_idx'),
		]


class SavedMovie(models.Model):
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='saved_movies')
	movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='saved_by')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		constraints = [
			models.UniqueConstraint(fields=('user', 'movie'), name='core_savedmovie_user_movie_uniq'),
		]
		ordering = ('-created_at',)


class ScrapeRun(models.Model):
	STATUS_CHOICES = (
		('running', 'Running'),
		('completed', 'Completed'),
		('failed', 'Failed'),
		('cancelled', 'Cancelled'),
	)

	started_at = models.DateTimeField(auto_now_add=True)
	finished_at = models.DateTimeField(null=True, blank=True)
	status = models.CharField(max_length=20, choices=STATUS_CHOICES)
	new_titles = models.PositiveIntegerField(default=0)
	total_titles = models.PositiveIntegerField(default=0)
	progress_current = models.PositiveIntegerField(default=0)
	progress_total = models.PositiveIntegerField(default=0)
	progress_message = models.CharField(max_length=255, blank=True)
	process_id = models.PositiveIntegerField(null=True, blank=True)
	error = models.TextField(blank=True)

	class Meta:
		constraints = [
			models.UniqueConstraint(
				fields=('status',),
				condition=models.Q(status='running'),
				name='core_scraperun_one_running',
			)
		]
		ordering = ('-started_at',)


class DownloadJob(models.Model):
	STATUS_CHOICES = (
		('starting', 'Starting'),
		('downloading', 'Downloading'),
		('pausing', 'Pausing'),
		('paused', 'Paused'),
		('cancelling', 'Cancelling'),
		('complete', 'Complete'),
		('error', 'Error'),
	)

	id = models.CharField(max_length=64, primary_key=True)
	user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)
	session_key = models.CharField(max_length=40, blank=True, db_index=True)
	video_url = models.URLField(max_length=500)
	download_format = models.CharField(max_length=30)
	status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='starting')
	progress = models.PositiveSmallIntegerField(default=0)
	downloaded_bytes = models.BigIntegerField(default=0)
	total_bytes = models.BigIntegerField(default=0)
	speed = models.FloatField(default=0)
	eta = models.FloatField(null=True, blank=True)
	detail = models.CharField(max_length=255, blank=True)
	filename = models.CharField(max_length=255, blank=True)
	path = models.CharField(max_length=500, blank=True)
	output_dir = models.CharField(max_length=500, blank=True)
	stop_requested = models.BooleanField(default=False)
	cancel_requested = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ('-created_at',)
