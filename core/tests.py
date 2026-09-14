from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from bs4 import BeautifulSoup

from .models import ActivityEvent, DownloadJob, Movie, SavedMovie, ScrapeRun
from .management.commands.scrape_movies import Command


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
		for index in range(25):
			Movie.objects.create(
				id=f'pagination-movie-{index}', title=f'Test Movie {index}',
				link=f'https://example.com/pagination-movie-{index}', category='pagination-test', scraped_at=timezone.now(),
			)
		response = Client().get(reverse('browse'), {'cat': 'pagination-test', 'page': 2})
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context['page_obj'].number, 2)
		self.assertEqual(response.context['page_obj'].paginator.count, 25)
		self.assertEqual(len(response.context['movies']), 1)
		self.assertEqual(response.context['total_movies'], 25)

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

	def test_download_creation_requires_post_and_csrf(self):
		response = self.client.get(reverse('youtube_download'), {'url': 'https://www.youtube.com/watch?v=abcdefghijk'})
		self.assertEqual(response.status_code, 405)
