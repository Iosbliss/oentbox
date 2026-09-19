from django.contrib.auth import get_user_model
from datetime import timedelta
import tempfile
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from bs4 import BeautifulSoup
from unittest.mock import patch

from .models import ActivityEvent, DownloadJob, Movie, SavedMovie, ScrapeRun
from . import views
from .management.commands.scrape_movies import Command
from .movie_data import classify_movie_category


@override_settings(SECURE_SSL_REDIRECT=False)
class DashboardTests(TestCase):
	def setUp(self):
		self.user = get_user_model().objects.create_user(
			username='staff', password='strong-test-password', is_staff=True,
		)
		self.client = Client()
		self.client.force_login(self.user)

	def test_dashboard_data_requires_staff(self):
		response = self.client.get(reverse('dashboard_data'))
		self.assertEqual(response.status_code, 200)
		self.assertIn('titles', response.json())
		self.assertIn('history', response.json())

	def test_categories_match_country_and_media_type(self):
		self.assertEqual(classify_movie_category('Wura Season 4', 'Nigerian series'), 'nollywood-tv-series')
		self.assertEqual(classify_movie_category('Single Black Tenant', 'American movie'), 'hollywood-movie')
		self.assertEqual(classify_movie_category('Love on the Menu Season 1', 'Korean Drama'), 'korean-drama')
		self.assertEqual(classify_movie_category('Fantastic Doctors Season 1', 'Chinese Drama'), 'chinese-drama')
		self.assertEqual(classify_movie_category('Romeo Akbar Walter', 'Bollywood Movie'), 'foreign-movie')

	def test_dashboard_data_includes_catalog_and_history(self):
		Movie.objects.create(id='movie-1', title='Test Movie', link='https://example.com/movie-1', category='hollywood', scraped_at=timezone.now())
		ScrapeRun.objects.create(status='completed', new_titles=1, total_titles=1)
		response = self.client.get(reverse('dashboard_data'))
		self.assertEqual(response.json()['history']['completed_runs'], 1)
		self.assertEqual(response.json()['titles'][0]['title'], 'Test Movie')

	def test_activity_rejects_oversized_fields(self):
		response = self.client.post(reverse('track_activity'), data={'event_type': 'download', 'movie_id': 'x' * 256})
		self.assertEqual(response.status_code, 400)
		self.assertEqual(ActivityEvent.objects.count(), 0)

	def test_scraper_ignores_generic_branding_image(self):
		soup = BeautifulSoup(
			'<meta property="og:image" content="https://9jarocks.net/logo.png">'
			'<img src="https://9jarocks.net/uploads/real-movie-poster.jpg">',
			'html.parser',
		)
		self.assertEqual(Command().extract_detail_thumbnail(soup), 'https://9jarocks.net/uploads/real-movie-poster.jpg')

	def test_browse_is_paginated(self):
		for index in range(53):
			Movie.objects.create(
				id=f'pagination-movie-{index}', title=f'Test Movie {index}',
				link=f'https://example.com/pagination-movie-{index}', category='pagination-test', scraped_at=timezone.now(),
			)
		response = Client().get(reverse('browse'), {'cat': 'pagination-test', 'page': 2})
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context['page_obj'].number, 2)
		self.assertEqual(response.context['page_obj'].paginator.count, 53)
		self.assertEqual(len(response.context['movies']), 1)
		self.assertEqual(response.context['total_movies'], 53)

	def test_saved_movies_are_account_isolated(self):
		movie = Movie.objects.create(
			id='saved-movie', title='Saved Movie', link='https://example.com/saved-movie',
			category='hollywood', scraped_at=timezone.now(),
		)
		other_user = get_user_model().objects.create_user(username='other', password='strong-test-password')
		SavedMovie.objects.create(user=self.user, movie=movie)
		self.client.force_login(other_user)
		response = self.client.get(reverse('saved'))
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context['movies'], [])

	def test_saved_api_returns_empty_list_for_guests(self):
		response = Client().get(reverse('saved_api'))
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json(), {'movie_ids': []})

	def test_activity_requires_csrf(self):
		csrf_client = Client(enforce_csrf_checks=True)
		response = csrf_client.post(reverse('track_activity'), data='{}', content_type='application/json')
		self.assertEqual(response.status_code, 403)

	def test_browse_filters_by_year_and_type(self):
		Movie.objects.create(
			id='filter-series', title='Filtered Series', link='https://example.com/filter-series',
			category='tv-series', year=2099, scraped_at=timezone.now(),
		)
		Movie.objects.create(
			id='filter-movie', title='Filtered Movie', link='https://example.com/filter-movie',
			category='hollywood', year=2025, scraped_at=timezone.now(),
		)
		response = Client().get(reverse('browse'), {'year': '2099', 'type': 'series'})
		self.assertEqual(response.context['total_movies'], 1)
		self.assertEqual(response.context['movies'][0]['id'], 'filter-series')

	def test_download_job_is_private_to_creator(self):
		job = DownloadJob.objects.create(
			id='private-job', session_key='owner-session', video_url='https://www.youtube.com/watch?v=abcdefghijk',
			download_format='video', detail='Preparing download...',
		)
		other_client = Client()
		other_client.session.save()
		response = other_client.get(reverse('youtube_download_status', args=[job.pk]))
		self.assertEqual(response.status_code, 404)

	def test_download_status_uses_persisted_progress(self):
		job = DownloadJob.objects.create(
			id='progress-job', user=self.user, video_url='https://www.youtube.com/watch?v=abcdefghijk',
			download_format='video', status='downloading', progress=47,
			detail='Downloading... 47%', downloaded_bytes=470, total_bytes=1000,
		)
		with views.DOWNLOAD_JOBS_LOCK:
			views.DOWNLOAD_JOBS[job.pk] = {'status': 'starting', 'progress': 0}
		response = self.client.get(reverse('youtube_download_status', args=[job.pk]))
		self.assertEqual(response.json()['status'], 'downloading')
		self.assertEqual(response.json()['progress'], 47)

	def test_download_file_uses_persisted_complete_path_when_memory_is_stale(self):
		with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as handle:
			handle.write(b'hello world')
			path = handle.name
		job = DownloadJob.objects.create(
			id='persisted-file-job', user=self.user, video_url='https://www.youtube.com/watch?v=abcdefghijk',
			download_format='audio_mp3', status='complete', progress=100,
			detail='Download ready.', filename='test-file.mp3', path=path, output_dir=str(__import__('os').path.dirname(path)),
		)
		with views.DOWNLOAD_JOBS_LOCK:
			views.DOWNLOAD_JOBS[job.pk] = {'status': 'starting', 'path': '', 'filename': 'stale.mp3'}
		response = self.client.get(reverse('youtube_download_file', args=[job.pk]))
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.get('Content-Disposition'), 'attachment; filename="test-file.mp3"')
		self.assertEqual(response.get('Content-Type'), 'audio/mpeg')

	def test_download_status_reports_actual_completed_file_size(self):
		with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as handle:
			handle.write(b'actual file bytes')
			path = handle.name
		job = DownloadJob.objects.create(
			id='actual-size-job', user=self.user, video_url='https://www.youtube.com/watch?v=abcdefghijk',
			download_format='audio_mp3', status='complete', progress=100,
			detail='Download ready.', filename='actual-file.mp3', path=path,
			total_bytes=12000000,
		)
		response = self.client.get(reverse('youtube_download_status', args=[job.pk]))
		self.assertEqual(response.json()['total_bytes'], 12000000)
		self.assertEqual(response.json()['file_size'], len(b'actual file bytes'))

	def test_stale_starting_download_is_expired(self):
		job = DownloadJob.objects.create(
			id='stale-job', user=self.user, video_url='https://www.youtube.com/watch?v=abcdefghijk',
			download_format='video', status='starting', detail='Preparing download...',
		)
		DownloadJob.objects.filter(pk=job.pk).update(
			updated_at=timezone.now() - timedelta(minutes=3),
		)
		response = self.client.get(reverse('youtube_download_status', args=[job.pk]))
		self.assertEqual(response.json()['status'], 'error')

	def test_health_check_reports_database(self):
		response = self.client.get(reverse('healthz'))
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json(), {'status': 'ok', 'database': 'ok'})

	def test_activity_accepts_youtube_event_types(self):
		for event_type in (ActivityEvent.YOUTUBE_SEARCH, ActivityEvent.YOUTUBE_DOWNLOAD):
			response = self.client.post(
				reverse('track_activity'),
				data={'event_type': event_type, 'movie_id': 'https://youtube.com/watch?v=test', 'movie_title': 'Test video'},
				content_type='application/json',
			)
			self.assertEqual(response.status_code, 200)

	def test_download_creation_requires_post_and_csrf(self):
		response = self.client.get(reverse('youtube_download'), {'url': 'https://www.youtube.com/watch?v=abcdefghijk'})
		self.assertEqual(response.status_code, 405)

	@override_settings(BEHIND_PROXY=True)
	def test_youtube_location_uses_forwarded_visitor_ip(self):
		request = RequestFactory().get(
			'/youtube.html',
			HTTP_X_FORWARDED_FOR='8.8.8.8, 127.0.0.1',
		)
		self.assertEqual(views._visitor_ip(request), '8.8.8.8')

	def test_youtube_publish_time_is_relative(self):
		published = timezone.now().timestamp() - (31 * 24 * 60 * 60)
		self.assertEqual(views._relative_publish_time({'timestamp': published}), '1 month ago')

	def test_youtube_publish_date_rejects_invalid_video_id(self):
		response = self.client.get(reverse('youtube_publish_date'), {'id': 'invalid'})
		self.assertEqual(response.status_code, 400)

	def test_download_pause_persists_control_state(self):
		job = DownloadJob.objects.create(
			id='pause-job', user=self.user, video_url='https://www.youtube.com/watch?v=abcdefghijk',
			download_format='video', status='downloading', output_dir='/tmp/pause-job',
		)
		with views.DOWNLOAD_JOBS_LOCK:
			views.DOWNLOAD_JOBS['pause-job'] = {'status': 'downloading'}
		response = self.client.post(reverse('youtube_download_pause', args=[job.pk]))
		job.refresh_from_db()
		self.assertEqual(response.json(), {'status': 'pausing'})
		self.assertEqual(job.status, 'pausing')
		self.assertTrue(job.stop_requested)

	def test_download_resume_spawns_worker_without_memory_state(self):
		job = DownloadJob.objects.create(
			id='resume-job', user=self.user, video_url='https://www.youtube.com/watch?v=abcdefghijk',
			download_format='video', status='paused', output_dir='/tmp/resume-job',
		)
		with patch('core.views._spawn_download_job') as spawn:
			response = self.client.post(reverse('youtube_download_resume', args=[job.pk]))
		job.refresh_from_db()
		self.assertEqual(response.json(), {'status': 'starting'})
		self.assertEqual(job.status, 'starting')
		spawn.assert_called_once_with(job.pk)

	def test_download_cancel_works_without_memory_state(self):
		job = DownloadJob.objects.create(
			id='cancel-job', user=self.user, video_url='https://www.youtube.com/watch?v=abcdefghijk',
			download_format='video', status='downloading', output_dir='/tmp/cancel-job',
		)
		response = self.client.post(reverse('youtube_download_cancel', args=[job.pk]))
		job.refresh_from_db()
		self.assertEqual(response.json(), {'status': 'cancelling'})
		self.assertTrue(job.cancel_requested)
		self.assertTrue(job.stop_requested)
