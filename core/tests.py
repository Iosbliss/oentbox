from django.contrib.auth import get_user_model
from datetime import timedelta
import json
import tempfile
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from bs4 import BeautifulSoup
from unittest.mock import patch

from .models import ActivityEvent, Movie, NewsletterEmail, SavedMovie, ScrapeRun
from . import views
from .management.commands.scrape_movies import Command
from .movie_data import classify_movie_category, load_movies


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
		self.assertEqual(classify_movie_category('Wura Season 4', 'Drama episode'), 'nollywood-tv-series')
		self.assertEqual(classify_movie_category('A New Love Story', 'Drama episode', category='nollywood-series', metadata='American TV series'), 'nollywood-tv-series')
		self.assertEqual(classify_movie_category('Bob Hearts Abishola Season 1', 'An American sitcom about a Nigerian immigrant'), 'hollywood-tv-series')
		self.assertEqual(classify_movie_category('Single Black Tenant', 'American movie'), 'hollywood-movie')
		self.assertEqual(classify_movie_category('Love on the Menu Season 1', 'Korean Drama'), 'korean-drama')
		self.assertEqual(classify_movie_category('Fantastic Doctors Season 1', 'Chinese Drama'), 'chinese-drama')
		self.assertEqual(classify_movie_category('Romeo Akbar Walter', 'Bollywood Movie'), 'bollywood-movie')
		self.assertEqual(
			classify_movie_category('Ordinary People Season 1', '', metadata={'Country': 'Nigeria'}),
			'nollywood-tv-series',
		)

	def test_rendering_preserves_stored_category(self):
		Movie.objects.create(
			id='stored-category', title='Wu Assassins Season 1',
			description='A Korean action series',
			link='https://example.com/stored-category',
			category='other-foreign-series', scraped_at=timezone.now(),
		)
		movie = load_movies()[0]
		self.assertEqual(movie['category'], 'other-foreign-series')

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

	def test_saved_api_requires_authentication(self):
		response = Client().get(reverse('saved_api'))
		self.assertEqual(response.status_code, 401)

	def test_activity_requires_csrf(self):
		csrf_client = Client(enforce_csrf_checks=True)
		response = csrf_client.post(reverse('track_activity'), data='{}', content_type='application/json')
		self.assertEqual(response.status_code, 403)

	def test_browse_filters_by_year_and_type(self):
		Movie.objects.create(
			id='filter-series', title='Filtered Series', link='https://example.com/filter-series',
			category='hollywood-tv-series', year=2099, scraped_at=timezone.now(),
		)
		Movie.objects.create(
			id='filter-movie', title='Filtered Movie', link='https://example.com/filter-movie',
			category='hollywood-movie', year=2025, scraped_at=timezone.now(),
		)
		response = Client().get(reverse('browse'), {'year': '2099', 'type': 'series'})
		self.assertEqual(response.context['total_movies'], 1)
		self.assertEqual(response.context['movies'][0]['id'], 'filter-series')

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

	def test_youtube_direct_download_rejects_non_youtube_urls(self):
		response = self.client.get(reverse('youtube_download_direct'), {'url': 'https://evil.example.com/file'})
		self.assertEqual(response.status_code, 400)

	def test_api_search_suppresses_short_queries(self):
		response = self.client.get(reverse('api_search'), {'q': 'a'})
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json(), {'results': []})

	def test_youtube_direct_download_rejects_unknown_format(self):
		response = self.client.get(reverse('youtube_download_direct'), {'url': 'https://www.youtube.com/watch?v=xeEJ9SbzSFA', 'format': 'iso'})
		self.assertEqual(response.status_code, 400)


	@patch('core.views._youtube_location_profile', return_value=('Trending near you', ('music',)))
	@patch('core.views._youtube_search', return_value=[])
	def test_youtube_search_clamps_expensive_result_limit(self, search, location):
		response = Client().get(reverse('youtube_search'), {'q': 'music', 'limit': 100})
		self.assertEqual(response.status_code, 200)
		search.assert_called_once_with('music', limit=24)
	def test_api_search_finds_matching_titles(self):
		response = self.client.get(reverse('api_search'), {'q': 'nollywood'})
		self.assertEqual(response.status_code, 200)

	def test_newsletter_signup_stores_email(self):
		response = self.client.post(
			reverse('newsletter_signup'),
			json.dumps({'email': 'fan@example.com', 'website': ''}),
			content_type='application/json',
		)
		self.assertEqual(response.status_code, 200)
		self.assertTrue(NewsletterEmail.objects.filter(email='fan@example.com').exists())

	def test_newsletter_signup_rejects_bad_email(self):
		response = self.client.post(
			reverse('newsletter_signup'),
			json.dumps({'email': 'not-an-email', 'website': ''}),
			content_type='application/json',
		)
		self.assertEqual(response.status_code, 400)

	def test_random_movie_redirects_to_a_title(self):
		response = self.client.get(reverse('random_movie'))
		self.assertEqual(response.status_code, 302)
		self.assertIn('/video_detail.html?id=', response['Location'])
