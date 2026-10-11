from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.models import Group
from django.shortcuts import render
from django.http import FileResponse, HttpResponse, HttpResponseRedirect, JsonResponse
from django.core.cache import cache
from django.core.paginator import Paginator
from django.middleware.csrf import get_token
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_protect
from .imageproxy import poster_url
import json
import hashlib
import ipaddress
import math
import threading
import logging
import os
import random
import re
import tempfile
import uuid
from datetime import datetime, timezone as datetime_timezone
from html import escape
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, urlparse
from functools import lru_cache
from django.conf import settings
from django.utils.text import get_valid_filename
from collections import Counter
from django.utils import timezone
from .models import ActivityEvent, Movie, NewsletterEmail, SavedMovie, ScrapeRun, Visit
from .seo import build_movie_schema
from .movie_data import (
    CATEGORY_LABELS,
    EXCLUDED_CATEGORIES,
    LEGACY_CATEGORY_ALIASES,
    get_featured_movies,
    get_movies_by_category,
    get_movie_by_id,
    get_categories,
    search_movies,
    count_movies,
    load_movies
)


SCRAPE_STATE = {
    'running': False,
    'error': '',
    'message': '',
    'current': 0,
    'total': 0,
}
SCRAPE_LOCK = threading.Lock()
logger = logging.getLogger(__name__)

# Mirror of the page whitelist in core/middleware.py, kept as a raw
# pattern so _visitor_stats can filter historical probe rows (e.g.
# /wp-login.php recorded before path filtering existed) directly in SQL.
_VISIT_PATH_PATTERN = (
	r'^/(?:'
	r'|index\.html|about\.html|privacy\.html|terms\.html'
	r'|youtube\.html|youtube/video\.html|browse\.html'
	r'|saved\.html|video_detail\.html|title\.html|random/)'
	r'$'
)


def _visitor_stats():
	"""Compute self-hosted visitor analytics for the dashboard."""
	try:
		from django.db.models import Count

		# Only genuine oentbox page views count; historical scanner-probe
		# rows must not show up as "visitors".
		visit_query = Visit.objects.filter(path__regex=_VISIT_PATH_PATTERN)
		total_visits = visit_query.count()
		unique_visitors = visit_query.values_list('ip_address', flat=True).distinct().count() if total_visits else 0
		today = timezone.localdate()
		visits_today = visit_query.filter(created_at__date=today).count()
		last_7_days = visit_query.filter(
			created_at__date__gte=today - timezone.timedelta(days=6),
		).values('created_at__date').annotate(count=Count('id')).order_by('created_at__date')
		visits_last_7_days = [
			{'date': item['created_at__date'].isoformat(), 'count': item['count']}
			for item in last_7_days
		]
		top_paths = list(
			visit_query
			.values('path')
			.annotate(view_count=Count('id'))
			.order_by('-view_count')[:10]
		)

		# Bot vs human split. Rows flagged by the tracking middleware or
		# backfilled by migration 0003 are counted directly; unflagged
		# unknown rows (shouldn't exist) fall back to signature matching.
		from .middleware import _is_bot

		bot_visits = visit_query.filter(is_bot=True).count()
		legacy_query = visit_query.filter(is_bot=False)
		legacy_total = legacy_query.count()
		if legacy_total:
			legacy_bot = 0
			for user_agent in legacy_query.values_list('user_agent', flat=True).iterator():
				if _is_bot(user_agent):
					legacy_bot += 1
			bot_visits += legacy_bot
			human_visits = legacy_total - legacy_bot

		# Top external referrers. The middleware stores the raw Referer
		# header, so group by host; direct traffic (no Referer header) is
		# counted separately as its own row.
		from urllib.parse import urlparse as _urlparse

		referrer_hosts = Counter()
		direct_visits = 0
		for referer in visit_query.values_list('referer', flat=True).iterator():
			if not referer:
				direct_visits += 1
				continue
			host = (_urlparse(referer).netloc or '').split(':')[0].lower()
			referrer_hosts[host or '(other)'] += 1
		if referrer_hosts.get('oentbox.com') or referrer_hosts.get('www.oentbox.com'):
			# Internal navigation noise (our own domain) is not a source.
			referrer_hosts.pop('oentbox.com', None)
			referrer_hosts.pop('www.oentbox.com', None)
			referrer_hosts.pop('104.234.124.234', None)
		top_referrers = [
			{'source': host, 'view_count': count}
			for host, count in referrer_hosts.most_common(8)
		]
		if direct_visits:
			top_referrers.insert(0, {'source': '(direct / none)', 'view_count': direct_visits})

		return {
			'total_visits': total_visits,
			'unique_visitors': unique_visitors,
			'visits_today': visits_today,
			'visits_last_7_days': visits_last_7_days,
			'top_paths': top_paths,
			'human_visits': human_visits,
			'bot_visits': bot_visits,
			'top_referrers': top_referrers,
		}
	except Exception as error:
		logger.warning('Visitor stats computation failed: %s', error)
		return {
			'total_visits': 0,
			'unique_visitors': 0,
			'visits_today': 0,
			'visits_last_7_days': [],
			'top_paths': [],
			'human_visits': 0,
			'bot_visits': 0,
			'top_referrers': [],
		}


def rate_limit(scope, limit, window):
    def decorator(view):
        def wrapped(request, *args, **kwargs):
            identity = request.user.pk if request.user.is_authenticated else _visitor_ip(request)
            key = f'oentbox:rate:{scope}:{identity}'
            try:
                count = cache.get(key)
                if count is None:
                    cache.add(key, 1, timeout=window)
                    count = 1
                else:
                    count = cache.incr(key)
            except ValueError:
                count = limit + 1
            if count > limit:
                return JsonResponse({'error': 'Too many requests. Try again shortly.'}, status=429, headers={'Retry-After': str(window)})
            return view(request, *args, **kwargs)
        wrapped.__name__ = view.__name__
        wrapped.__doc__ = view.__doc__
        return wrapped
    return decorator

YOUTUBE_DISCOVERY_QUERIES = (
    'YouTube trending now', 'trending videos today', 'most viewed videos today',
    'viral videos this week', 'popular videos near me', 'YouTube popular now',
)
YOUTUBE_LOCATION_PROFILES = {
    'NG': ('Trending in Nigeria', (
        'YouTube trending Nigeria', 'trending videos Nigeria today',
        'most viewed videos Nigeria', 'viral videos Nigeria this week',
        'popular videos Nigeria now',
    )),
    'GH': ('Trending in Ghana', (
        'YouTube trending Ghana', 'trending videos Ghana today',
        'most viewed videos Ghana', 'viral videos Ghana this week',
        'popular videos Ghana now',
    )),
    'KE': ('Trending in Kenya', (
        'YouTube trending Kenya', 'trending videos Kenya today',
        'most viewed videos Kenya', 'viral videos Kenya this week',
        'popular videos Kenya now',
    )),
    'ZA': ('Trending in South Africa', (
        'YouTube trending South Africa', 'trending videos South Africa today',
        'most viewed videos South Africa', 'viral videos South Africa this week',
        'popular videos South Africa now',
    )),
}
YOUTUBE_HOSTS = {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'}
YOUTUBE_ID_RE = re.compile(r'^[A-Za-z0-9_-]{11}$')


def update_scrape_progress(message, current=0, total=0):
    with SCRAPE_LOCK:
        SCRAPE_STATE.update(message=message, current=current, total=total)


def resolve_category_slug(category):
    return LEGACY_CATEGORY_ALIASES.get(category, category)


def service_worker(request):
    """Serves the service worker from the site root so its default scope is
    '/' (a worker registered from /static/js/sw.js would default to a
    /static/js/ scope and never control the actual pages)."""
    sw_path = Path(__file__).resolve().parent.parent / 'static' / 'js' / 'sw.js'
    try:
        content = sw_path.read_text()
    except OSError:
        return JsonResponse({'error': 'Service worker unavailable.'}, status=404)
    response = HttpResponse(content, content_type='application/javascript')
    response['Service-Worker-Allowed'] = '/'
    response['Cache-Control'] = 'no-cache'
    return response


@require_GET
def healthz(request):
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        return JsonResponse({'status': 'ok', 'database': 'ok'})
    except Exception as error:
        logger.exception('Health check failed: %s', error)
        return JsonResponse({'status': 'error', 'database': 'unavailable'}, status=503)


def robots(request):
    sitemap_url = request.build_absolute_uri('/sitemap.xml')
    return HttpResponse(f'User-agent: *\nAllow: /\nDisallow: /admin/\nDisallow: /api/\nSitemap: {sitemap_url}\n', content_type='text/plain')


def favicon(request):
    favicon_path = Path(__file__).resolve().parent.parent / 'static' / 'img' / 'favicon.ico'
    try:
        return FileResponse(open(favicon_path, 'rb'), content_type='image/x-icon')
    except OSError:
        return HttpResponse(status=404)


def sitemap(request):
    base_url = request.build_absolute_uri('/').rstrip('/')
    static_paths = ('/', '/about.html', '/browse.html?cat=all', '/youtube.html')
    movies = Movie.objects.values('id', 'scraped_at').order_by('-scraped_at')[:5000]
    urls = [(f'{base_url}{path}', '') for path in static_paths]
    urls.extend(
        (f'{base_url}/video_detail.html?id={quote(movie["id"])}', movie['scraped_at'].date().isoformat())
        for movie in movies
    )
    body = ''.join(
        f'<url><loc>{escape(url)}</loc>{f"<lastmod>{lastmod}</lastmod>" if lastmod else ""}</url>'
        for url, lastmod in urls
    )
    return HttpResponse(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>', content_type='application/xml')


def youtube_page(request):
    get_token(request)
    location_name, queries = _youtube_location_profile(request)
    return render(request, "youtube.html", {
        'youtube_location': location_name,
        'youtube_chips': [
            {'label': location_name, 'query': ''},
            *({'label': query, 'query': query} for query in queries[1:]),
        ],
    })


def _format_duration(seconds):
    if not seconds:
        return ''
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours}:{minutes:02d}:{seconds:02d}' if hours else f'{minutes}:{seconds:02d}'


def _format_number(value):
    if value is None:
        return ''
    value = int(value)
    for suffix, divisor in (('B', 1_000_000_000), ('M', 1_000_000), ('K', 1_000)):
        if value >= divisor:
            return f'{value / divisor:.1f}{suffix}'.replace('.0', '')
    return str(value)


def _relative_publish_time(item):
    timestamp = item.get('timestamp')
    if timestamp:
        published_at = datetime.fromtimestamp(float(timestamp), tz=datetime_timezone.utc)
    else:
        upload_date = str(item.get('upload_date') or '')
        try:
            published_at = datetime.strptime(upload_date, '%Y%m%d').replace(tzinfo=datetime_timezone.utc)
        except ValueError:
            return ''

    elapsed_seconds = max(0, int((timezone.now() - published_at).total_seconds()))
    units = (
        ('year', 365 * 24 * 60 * 60),
        ('month', 30 * 24 * 60 * 60),
        ('week', 7 * 24 * 60 * 60),
        ('day', 24 * 60 * 60),
        ('hour', 60 * 60),
        ('minute', 60),
    )
    for label, seconds in units:
        if elapsed_seconds >= seconds:
            count = elapsed_seconds // seconds
            return f'{count} {label}{"s" if count != 1 else ""} ago'
    return 'Just now'


@lru_cache(maxsize=512)
def _youtube_publish_time(video_id):
    import yt_dlp

    options = {'quiet': True, 'no_warnings': True, 'skip_download': True}
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(f'https://www.youtube.com/watch?v={video_id}', download=False)
    return _relative_publish_time(info)


def _channel_url_from_item(item):
    """yt-dlp's flat/search extraction frequently omits channel_id, but usually
    still provides channel_url or uploader_url (or at least uploader_id, a
    '@handle'). Fall back through all of them so avatar hydration has the best
    chance of finding a usable channel URL."""
    channel_id = item.get('channel_id') or ''
    uploader_id = item.get('uploader_id') or ''
    return (
        item.get('channel_url')
        or item.get('uploader_url')
        or (f'https://www.youtube.com/channel/{channel_id}' if channel_id else '')
        or (f'https://www.youtube.com/{uploader_id}' if uploader_id.startswith('@') else '')
    )


def _video_summary(item):
    video_id = item.get('id')
    return {
        'id': video_id,
        'channel_id': item.get('channel_id') or '',
        'channel_url': _channel_url_from_item(item),
        'title': item.get('title') or 'Untitled video',
        'channel': item.get('channel') or item.get('uploader') or 'YouTube creator',
        'channel_thumbnail': item.get('channel_favicon') or item.get('uploader_favicon') or item.get('channel_thumbnail') or '',
        'duration': item.get('duration_string') or _format_duration(item.get('duration')),
        'published': _relative_publish_time(item),
        'views': _format_number(item.get('view_count')),
        'likes': _format_number(item.get('like_count')),
        'thumbnail': item.get('thumbnail') or f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg',
        'url': f'https://www.youtube.com/watch?v={video_id}',
    }


def _youtube_result_score(item, summary, position, query):
    """Rank results using provider relevance plus local quality signals."""
    query_terms = set(re.findall(r'\w+', query.lower()))
    searchable_text = f"{summary['title']} {summary['channel']}".lower()
    matched_terms = sum(term in searchable_text for term in query_terms)
    relevance = 1 / (position + 1)
    personalization = matched_terms / len(query_terms) if query_terms else 0

    views = max(item.get('view_count') or 0, 0)
    likes = max(item.get('like_count') or 0, 0)
    engagement = math.log1p(views) + (2 * math.log1p(likes))
    quality = (
        math.log1p(item.get('width') or 0)
        + math.log1p(item.get('height') or 0)
        + math.log1p(item.get('duration') or 0) / 4
    )
    return (
        (relevance * 100)
        + (personalization * 35)
        + (engagement * 2)
        + quality
    )


def _format_size_label(size):
    return f'{size / (1024 * 1024):.1f} MB' if size else 'Available after download'


def _estimate_download_sizes(formats, duration=0):
    known = [item for item in formats if item.get('filesize') or item.get('filesize_approx') or ((item.get('tbr') or item.get('abr')) and duration)]
    audio = [item for item in known if item.get('vcodec') == 'none']
    video = [item for item in known if item.get('vcodec') != 'none']

    def size(item):
        known_size = item.get('filesize') or item.get('filesize_approx')
        if known_size:
            return known_size
        bitrate = item.get('tbr') or item.get('abr') or 0
        return bitrate * 1000 * duration / 8 if bitrate and duration else 0

    def estimate(height=None):
        matching_video = [item for item in video if not height or (item.get('height') or 0) <= height]
        if height and matching_video:
            available_heights = [item.get('height') or 0 for item in matching_video]
            closest_height = max(available_heights)
            matching_video = [item for item in matching_video if (item.get('height') or 0) == closest_height]
        combined = [item for item in matching_video if item.get('acodec') != 'none']
        if combined:
            return max(map(size, combined))
        best_video = max((size(item) for item in matching_video), default=0)
        best_audio = max((size(item) for item in audio), default=0)
        if not best_video and height:
            bitrate = max((item.get('tbr') or item.get('vbr') or 0 for item in matching_video), default=0)
            best_video = bitrate * 1000 * duration / 8 if bitrate and duration else 0
        if best_video:
            return best_video + best_audio
        if height:
            overall_video = max((size(item) for item in video), default=0)
            max_height = max((item.get('height') or 0 for item in video), default=0)
            scaled_video = overall_video * height / max_height if overall_video and max_height else 0
            return scaled_video + best_audio
        return best_audio

    audio_size = max((size(item) for item in audio), default=0)
    audio_size = audio_size or (128 * 1000 * duration / 8 if duration else 0)
    mp3_size = 192 * 1000 * duration / 8 if duration else audio_size
    video_size = estimate()
    video_720_size = estimate(720)
    video_480_size = estimate(480)
    if duration and video_720_size == video_480_size:
        video_720_size = (2500 * 1000 * duration / 8) + audio_size
        video_480_size = (1000 * 1000 * duration / 8) + audio_size
    return {
        'video': _format_size_label(video_size),
        'video_720': _format_size_label(video_720_size),
        'video_480': _format_size_label(video_480_size),
        'audio': _format_size_label(audio_size),
        'audio_mp3': _format_size_label(mp3_size),
    }


def _video_comments(info, limit=30):
    comments = []
    for item in (info.get('comments') or [])[:limit]:
        text = (item.get('text') or item.get('comment_text') or '').strip()
        if not text:
            continue
        comments.append({
            'author': item.get('author') or 'YouTube user',
            'text': text,
            'likes': _format_number(item.get('like_count')),
            'author_thumbnail': item.get('author_thumbnail') or '',
        })
    return comments


def _thumbnail_from_youtubei(value):
    if isinstance(value, dict):
        if value.get('avatar') and isinstance(value['avatar'], dict):
            thumbnails = value['avatar'].get('thumbnails') or []
            if thumbnails:
                return thumbnails[-1].get('url') or ''
        for child in value.values():
            thumbnail = _thumbnail_from_youtubei(child)
            if thumbnail:
                return thumbnail
    elif isinstance(value, list):
        for child in value:
            thumbnail = _thumbnail_from_youtubei(child)
            if thumbnail:
                return thumbnail
    return ''


@lru_cache(maxsize=128)
def _channel_thumbnail(channel_url, channel_id=''):
    if not channel_url and not channel_id:
        return ''
    try:
        import yt_dlp
        import requests

        if channel_id:
            response = requests.post(
                'https://www.youtube.com/youtubei/v1/browse?prettyPrint=false',
                json={
                    'context': {'client': {'clientName': 'WEB', 'clientVersion': '2.20260101.00.00'}},
                    'browseId': channel_id,
                },
                headers={'Origin': 'https://www.youtube.com', 'User-Agent': 'Mozilla/5.0'},
                timeout=8,
            )
            if response.ok:
                thumbnail = _thumbnail_from_youtubei(response.json())
                if thumbnail:
                    return thumbnail

        options = {'quiet': True, 'no_warnings': True, 'skip_download': True}
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(channel_url, download=False)
        direct_thumbnail = (
            info.get('channel_favicon')
            or info.get('uploader_favicon')
            or info.get('channel_thumbnail')
            or info.get('uploader_thumbnail')
            or ''
        )
        if direct_thumbnail:
            return direct_thumbnail
        thumbnails = info.get('thumbnails') or []
        avatar = next((item.get('url') for item in thumbnails if item.get('id') == 'avatar_uncropped'), '')
        return avatar or next((item.get('url') for item in reversed(thumbnails) if item.get('url')), '')
    except Exception as error:
        logger.debug('YouTube channel thumbnail failed: %s', error)
        return ''


@lru_cache(maxsize=64)
def _youtube_search(query, limit=12):
    import yt_dlp

    search_term = query or YOUTUBE_DISCOVERY_QUERIES[0]
    options = {'quiet': True, 'no_warnings': True, 'skip_download': True, 'extract_flat': True}
    with yt_dlp.YoutubeDL(options) as downloader:
        result = downloader.extract_info(f'ytsearch{limit}:{search_term}', download=False)
    videos = []
    for item in (result or {}).get('entries', []):
        video_id = item.get('id')
        if not video_id or not YOUTUBE_ID_RE.match(video_id):
            continue
        videos.append((item, _video_summary(item)))

    summaries = [
        summary for _, summary, _ in sorted(
            (
                (item, summary, position)
                for position, (item, summary) in enumerate(videos)
            ),
            key=lambda result: _youtube_result_score(
                result[0], result[1], result[2], query,
            ),
            reverse=True,
        )
    ]
    # Publish dates and avatars are hydrated asynchronously by the browser.
    # Keeping those lookups out of this request prevents slow upstream calls
    # from blocking a Gunicorn worker.
    return summaries


def _visitor_feed_random(request):
    visitor_ip, _ = _request_location(request)
    day = timezone.localdate().isoformat()
    seed = hashlib.sha256(f'{visitor_ip}:{day}'.encode()).hexdigest()
    return random.Random(seed)


@lru_cache(maxsize=256)
def _location_profile(country_code):
    return YOUTUBE_LOCATION_PROFILES.get(country_code, ('Trending near you', YOUTUBE_DISCOVERY_QUERIES))


def _visitor_ip(request):
    remote_addr = request.META.get('REMOTE_ADDR', '')
    if getattr(settings, 'BEHIND_PROXY', False):
        forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if forwarded_for:
            candidate = forwarded_for.split(',')[0].strip()
            if candidate:
                return candidate
        real_ip = request.META.get('HTTP_X_REAL_IP', '').strip()
        if real_ip:
            return real_ip
    return remote_addr or 'unknown'


def _request_location(request):
    visitor_ip = _visitor_ip(request)
    cache_key = f'youtube-location-v2:{hashlib.sha256(visitor_ip.encode()).hexdigest()[:24]}'
    cached = cache.get(cache_key)
    if cached:
        return cached['ip'], cached

    try:
        parsed_ip = ipaddress.ip_address(visitor_ip)
    except ValueError:
        parsed_ip = None

    lookup_url = f'https://ipapi.co/{visitor_ip}/json/' if parsed_ip and not parsed_ip.is_private and not parsed_ip.is_loopback else 'https://ipapi.co/json/'
    location = {}
    try:
        import requests
        response = requests.get(lookup_url, timeout=3)
        if response.ok:
            location = response.json()
    except Exception as error:
        logger.debug('Primary YouTube IP location lookup failed: %s', error)

    if not location.get('country_code'):
        try:
            import requests
            fallback_url = 'https://ipwho.is/' if not parsed_ip or parsed_ip.is_private or parsed_ip.is_loopback else f'https://ipwho.is/{visitor_ip}'
            response = requests.get(fallback_url, timeout=3)
            if response.ok:
                location = response.json()
        except Exception as error:
            logger.debug('Fallback YouTube IP location lookup failed: %s', error)

    details = {
        'ip': location.get('ip') or visitor_ip,
        'country_code': (location.get('country_code') or location.get('country') or '').upper(),
        'city': location.get('city') or '',
    }
    cache.set(cache_key, details, 86400)
    return details['ip'], details


def _youtube_location_profile(request):
    _, location = _request_location(request)
    profile_name, queries = _location_profile(location['country_code'])
    return profile_name, queries


@rate_limit('youtube-search', 30, 60)
@require_GET
def youtube_search(request):
    query = request.GET.get('q', '').strip()
    if len(query) > 100:
        return JsonResponse({'error': 'Search is limited to 100 characters.'}, status=400)
    try:
        limit = int(request.GET.get('limit', 12))
    except ValueError:
        limit = 12
    limit = max(6, min(limit, 24))
    feed_random = _visitor_feed_random(request)
    _, discovery_queries = _youtube_location_profile(request)
    resolved_query = query or feed_random.choice(discovery_queries)
    try:
        videos = list(_youtube_search(resolved_query, limit=limit))
        if not query:
            feed_random.shuffle(videos)
        ActivityEvent.objects.create(
            movie_id=resolved_query[:255],
            movie_title=query[:255] or resolved_query[:255],
            event_type=ActivityEvent.YOUTUBE_SEARCH,
        )
        return JsonResponse({'query': query, 'resolved_query': resolved_query, 'videos': videos})
    except Exception as error:
        logger.warning('YouTube search failed: %s', error)
        return JsonResponse({'error': 'YouTube search is temporarily unavailable.'}, status=502)


@rate_limit('youtube-publish-date', 60, 60)
@require_GET
def youtube_publish_date(request):
    video_id = request.GET.get('id', '').strip()
    if not YOUTUBE_ID_RE.match(video_id):
        return JsonResponse({'error': 'Invalid YouTube video ID.'}, status=400)
    try:
        return JsonResponse({'published': _youtube_publish_time(video_id)})
    except Exception as error:
        logger.debug('YouTube publish date failed: %s', error)
        return JsonResponse({'published': ''})


CHANNEL_PATH_RE = re.compile(
    r'^/(channel/UC[A-Za-z0-9_-]{22}|@[\w.-]{1,100}|c/[\w.-]{1,100}|user/[\w.-]{1,100})/?$'
)


@require_GET
def youtube_channel_avatar(request):
    channel_url = request.GET.get('url', '').strip()
    channel_id = request.GET.get('id', '').strip()
    if not channel_url and channel_id and re.match(r'^UC[A-Za-z0-9_-]{22}$', channel_id):
        channel_url = f'https://www.youtube.com/channel/{channel_id}'

    parsed = urlparse(channel_url)
    channel_match = re.match(r'^/channel/(UC[A-Za-z0-9_-]{22})/?$', parsed.path)
    if not channel_id and channel_match:
        channel_id = channel_match.group(1)
    is_valid = (
        parsed.scheme == 'https'
        and parsed.netloc in YOUTUBE_HOSTS
        and CHANNEL_PATH_RE.match(parsed.path)
    )
    if not is_valid:
        return JsonResponse({'error': 'Invalid channel.'}, status=400)

    thumbnail = _channel_thumbnail(channel_url, channel_id)
    return JsonResponse({'thumbnail': thumbnail})


@require_GET
def youtube_video_detail(request):
    get_token(request)
    video_id = request.GET.get('id', '').strip()
    if not YOUTUBE_ID_RE.match(video_id):
        return render(request, 'youtube_detail.html', {'error': 'This video could not be found.'}, status=404)
    video_url = f'https://www.youtube.com/watch?v={video_id}'
    cache_key = f'yt:detail:{video_id}'
    cached = cache.get(cache_key)
    if cached:
        video = cached['video']
        comments = cached['comments']
        upload_date = cached['upload_date']
        similar = _youtube_search(video.get('channel') or video.get('title') or 'YouTube', limit=30)
        similar = [item for item in similar if item['id'] != video_id]
        for index, item in enumerate(similar):
            if index < 12 and not item['channel_thumbnail']:
                item['channel_thumbnail'] = _channel_thumbnail(item['channel_url'], item['channel_id'])
    else:
        try:
            import yt_dlp

            options = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'format': 'best[ext=mp4]/best',
                'getcomments': True,
                'extractor_args': {
                    'youtube': {
                        'comment_sort': ['top'],
                        'max_comments': ['30'],
                        'player_client': ['android', 'web_safari', 'tv'],
                    },
                },
            }
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(video_url, download=False)
            video = _video_summary(info)
            video['stream_url'] = info.get('url') or ''
            video['channel_id'] = video['channel_id'] or info.get('channel_id') or ''
            video['channel_url'] = video['channel_url'] or _channel_url_from_item(info)
            video['channel_thumbnail'] = video['channel_thumbnail'] or _channel_thumbnail(
                video['channel_url'], video['channel_id'],
            )
            video['description'] = (info.get('description') or '').strip()
            comments = _video_comments(info)
            video['format_sizes'] = _estimate_download_sizes(info.get('formats', []), info.get('duration') or 0)
            video['file_size'] = video['format_sizes']['video']
            upload_date = info.get('upload_date') or ''
            # Stream URLs stay valid for ~6h; a 3h cache keeps playback safe
            # while making repeat visits and crawler hits near-instant.
            cache.set(cache_key, {'video': video, 'comments': comments, 'upload_date': upload_date}, 60 * 60 * 3)
            similar = _youtube_search(info.get('channel') or info.get('title') or 'YouTube', limit=30)
            similar = [item for item in similar if item['id'] != video_id]
            for index, item in enumerate(similar):
                if index < 12 and not item['channel_thumbnail']:
                    item['channel_thumbnail'] = _channel_thumbnail(item['channel_url'], item['channel_id'])
        except Exception as error:
            logger.warning('YouTube detail failed: %s', error)
            return render(request, 'youtube_detail.html', {'error': 'Video details are temporarily unavailable.'}, status=502)
    return render(request, 'youtube_detail.html', {
        'video': video,
        'comments': comments,
        'similar_videos': similar,
        'canonical_url': request.build_absolute_uri(f'/youtube/video.html?id={quote(video_id)}'),
        'seo_json': _json_ld({
            '@context': 'https://schema.org',
            '@type': 'VideoObject',
            'name': video['title'],
            'description': video['description'][:500] or video['title'],
            'thumbnailUrl': video['thumbnail'],
            'uploadDate': upload_date,
            'contentUrl': video_url,
            'embedUrl': f'https://www.youtube.com/embed/{video_id}',
        }),
    })


class _DownloadPaused(Exception):
    """Raised inside the yt-dlp progress hook to unwind cleanly on pause/cancel."""


def _cleanup_download_dir(output_dir):
    try:
        for file in output_dir.glob('*'):
            file.unlink(missing_ok=True)
        output_dir.rmdir()
    except OSError:
        pass


YOUTUBE_DOWNLOAD_FORMATS = {
    'video': ('bestvideo*+bestaudio/bestvideo*/best', 'mp4'),
    'video_720': ('bestvideo*[height<=720]+bestaudio/best[height<=720]/best', 'mp4'),
    'video_480': ('bestvideo*[height<=480]+bestaudio/best[height<=480]/best', 'mp4'),
    'audio': ('bestaudio/best', 'm4a'),
    'audio_mp3': ('bestaudio/best', 'mp3'),
}


DIRECT_DOWNLOAD_SLOTS = threading.BoundedSemaphore(2)


@rate_limit('youtube-download-direct', 6, 60)
@require_GET
def youtube_download_direct(request):
    """Stream a YouTube file straight to the browser as an attachment."""
    video_url = request.GET.get('url', '').strip()
    download_format = request.GET.get('format', 'video').strip().lower()
    parsed = urlparse(video_url)
    if parsed.scheme not in {'http', 'https'} or (parsed.hostname or '').lower() not in YOUTUBE_HOSTS:
        return JsonResponse({'error': 'Only YouTube video URLs are supported.'}, status=400)
    if download_format not in YOUTUBE_DOWNLOAD_FORMATS:
        return JsonResponse({'error': 'Unsupported download format.'}, status=400)
    if not DIRECT_DOWNLOAD_SLOTS.acquire(blocking=False):
        return JsonResponse({'error': 'The server is busy with other downloads. Please try again shortly.'}, status=503, headers={'Retry-After': '30'})

    selected_format, extension = YOUTUBE_DOWNLOAD_FORMATS[download_format]
    output_dir = Path(tempfile.mkdtemp(prefix='oentbox-direct-'))
    output_template = str(output_dir / '%(title).120s.%(ext)s')
    try:
        import yt_dlp

        options = {
            'quiet': True,
            'no_warnings': True,
            'format': selected_format,
            'noplaylist': True,
            'retries': 3,
            'fragment_retries': 3,
            'extractor_args': {'youtube': {'player_client': ['android', 'web_safari', 'tv']}},
            'outtmpl': output_template,
            'continuedl': True,
            'nopart': False,
        }
        if download_format.startswith('video'):
            options['merge_output_format'] = 'mp4'
        if download_format == 'audio_mp3':
            options['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(video_url, download=True)
        files = [file for file in output_dir.iterdir() if file.is_file() and not file.name.endswith('.part')]
        if not files:
            raise RuntimeError('No downloaded file was produced.')
        filename = get_valid_filename(info.get('title') or 'youtube-video')
        filename = f'{filename[:120]}.{extension}'
        response = FileResponse(open(files[0], 'rb'), as_attachment=True, filename=filename)
        response['X-Content-Type-Options'] = 'nosniff'
        response._resource_closers.append(lambda: _cleanup_download_dir(output_dir))
        ActivityEvent.objects.create(
            movie_id=video_url,
            movie_title=info.get('title') or 'YouTube video',
            event_type=ActivityEvent.YOUTUBE_DOWNLOAD,
        )
        return response
    except Exception as error:
        _cleanup_download_dir(output_dir)
        logger.warning('Direct YouTube download failed: %s', error)
        return JsonResponse({'error': 'The video could not be downloaded. Please try again.'}, status=502)
    finally:
        DIRECT_DOWNLOAD_SLOTS.release()




def home(request):
    """Home page with featured movies"""
    featured_movies = get_featured_movies(limit=12)
    
    # Get movies by category for different sections
    home_row_limit = 16
    nollywood = get_movies_by_category('nollywood-movie', limit=home_row_limit)
    korean_drama = get_movies_by_category('korean-drama', limit=home_row_limit)
    hollywood = get_movies_by_category('hollywood-movie', limit=home_row_limit)
    tv_series = get_movies_by_category('hollywood-tv-series', limit=home_row_limit)
    anime = get_movies_by_category('anime', limit=home_row_limit)
    additional_categories = [
        ('Nollywood Series', 'nollywood-tv-series'),
        ('Bollywood Movies', 'bollywood-movie'),
        ('Bollywood Series', 'bollywood-tv-series'),
        ('Foreign Movies', 'foreign-movie'),
        ('Other Foreign Series', 'other-foreign-series'),
        ('Chinese Drama', 'chinese-drama'),
        ('Japanese Drama', 'japanese-drama'),
        ('Filipino Drama', 'filipino-drama'),
        ('Turkish Drama', 'turkish-drama'),
        ('Thai Drama', 'thai-drama'),
    ]
    additional_category_sections = [
        {
            'label': label,
            'slug': slug,
            'movies': get_movies_by_category(slug, limit=home_row_limit),
        }
        for label, slug in additional_categories
    ]
    
    context = {
        'featured_movies': featured_movies,
        'nollywood_movies': nollywood,
        'korean_drama_movies': korean_drama,
        'hollywood_movies': hollywood,
        'tv_series_movies': tv_series,
        'anime_movies': anime,
        'additional_category_sections': additional_category_sections,
        'has_movies': len(featured_movies) > 0
    }
    get_token(request)
    return render(request, "index.html", context)


@staff_member_required(login_url="/admin/login/")
def admin_dashboard(request):
    """Show the custom catalog dashboard to staff users."""
    user_model = get_user_model()
    context = {
        'dashboard_titles': dashboard_titles(),
        'dashboard_activity': [
            {'event_type': event.event_type, 'created_at': event.created_at.isoformat()}
            for event in ActivityEvent.objects.order_by('-created_at')[:500]
        ],
        'admin_user_count': user_model.objects.count(),
        'admin_staff_count': user_model.objects.filter(is_staff=True).count(),
        'admin_group_count': Group.objects.count(),
        'admin_active_count': user_model.objects.filter(is_active=True).count(),
        'admin_recent_users': user_model.objects.order_by('-date_joined')[:5],
        'visitor_stats': _visitor_stats(),
    }
    return render(request, "dashboard.html", context)


def dashboard_titles():
    result = []
    for movie in load_movies():
        video_info = movie.get('video_info') or {}
        result.append({
            'id': movie.get('id', ''), 'title': movie.get('title', ''),
            'category': movie.get('category', 'unknown'),
            'type': video_info.get('Type') or ('TV Series' if movie.get('category', '').endswith('-tv-series') else 'Movie'),
            'year': movie.get('year') or video_info.get('Year') or '',
            'thumbnail': bool(movie.get('thumbnail')),
            'scraped_at': movie.get('scraped_at', ''),
            'download_count': len(movie.get('download_links') or []),
        })
    return result


@staff_member_required(login_url="/admin/login/")
def dashboard_data(request):
    with SCRAPE_LOCK:
        state = dict(SCRAPE_STATE)
    titles = dashboard_titles()
    runs = list(ScrapeRun.objects.all()[:20])
    completed = [run for run in runs if run.status == 'completed']
    catalog_dates = Counter(title['scraped_at'][:10] for title in titles if title['scraped_at'])
    return JsonResponse({
        'titles': titles,
        'activity': [
            {'event_type': event.event_type, 'created_at': event.created_at.isoformat()}
            for event in ActivityEvent.objects.order_by('-created_at')[:500]
        ],
        'scraper': state,
        'visitor_stats': _visitor_stats(),
        'history': {
            'total_runs': ScrapeRun.objects.count(),
            'completed_runs': ScrapeRun.objects.filter(status='completed').count(),
            'failed_runs': ScrapeRun.objects.filter(status='failed').count(),
            'average_new_titles': round(sum(run.new_titles for run in completed) / len(completed), 1) if completed else 0,
            'catalog_days': len(catalog_dates),
            'average_titles_per_day': round(sum(catalog_dates.values()) / len(catalog_dates), 1) if catalog_dates else 0,
            'catalog_history': [
                {'started_at': date, 'status': 'catalog', 'new_titles': count, 'total_titles': count, 'error': ''}
                for date, count in sorted(catalog_dates.items(), reverse=True)[:20]
            ],
            'runs': [
                {'started_at': run.started_at.isoformat(), 'status': run.status,
                 'new_titles': run.new_titles, 'total_titles': run.total_titles,
                 'error': run.error}
                for run in runs
            ],
        },
    })


@staff_member_required(login_url="/admin/login/")
@require_POST
def run_scraper(request):
    """Start the automatic movie scraper without blocking the dashboard."""
    with SCRAPE_LOCK:
        if ScrapeRun.objects.filter(status='running').exists():
            return JsonResponse({'started': False, 'running': True}, status=409)
        SCRAPE_STATE['running'] = True
        SCRAPE_STATE['error'] = ''
        SCRAPE_STATE['message'] = 'Starting scraper...'
        SCRAPE_STATE['current'] = 0
        SCRAPE_STATE['total'] = 0

    started_count = count_movies()
    try:
        scrape_run = ScrapeRun.objects.create(status='running', total_titles=started_count)
    except Exception:
        with SCRAPE_LOCK:
            SCRAPE_STATE['running'] = False
        return JsonResponse({'started': False, 'running': True}, status=409)

    import subprocess
    import sys
    log_path = Path(tempfile.gettempdir()) / f'oentbox-scrape-{scrape_run.pk}.log'
    try:
        with log_path.open('ab') as log_handle:
            worker = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve().parent.parent / 'manage.py'),
                 'run_scrape_job', '--run-id', str(scrape_run.pk)],
                cwd=str(Path(__file__).resolve().parent.parent),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                close_fds=True,
                start_new_session=True,
            )
            ScrapeRun.objects.filter(pk=scrape_run.pk).update(process_id=worker.pid)
    except OSError as error:
        ScrapeRun.objects.filter(pk=scrape_run.pk).update(
            status='failed', error=str(error), progress_message='Worker could not start',
            finished_at=timezone.now(),
        )
        return JsonResponse({'started': False, 'running': False, 'error': str(error)}, status=503)
    return JsonResponse({'started': True, 'running': True, 'run_id': scrape_run.pk}, status=202)


@staff_member_required(login_url="/admin/login/")
@require_POST
def stop_scraper(request):
    """Stop the active scraper worker and mark its run as cancelled."""
    run = ScrapeRun.objects.filter(status='running').first()
    if not run:
        return JsonResponse({'stopped': False, 'running': False}, status=409)
    if run.process_id:
        try:
            os.kill(run.process_id, 15)
        except ProcessLookupError:
            pass
        except OSError as error:
            logger.warning('Could not stop scraper process %s: %s', run.process_id, error)
    run.status = 'cancelled'
    run.progress_message = 'Scrape stopped'
    run.finished_at = timezone.now()
    run.save(update_fields=['status', 'progress_message', 'finished_at'])
    with SCRAPE_LOCK:
        SCRAPE_STATE.update(running=False, message='Scrape stopped')
    return JsonResponse({'stopped': True, 'running': False})


@staff_member_required(login_url="/admin/login/")
def scraper_status(request):
    """Return the current background scraper state for the dashboard."""
    with SCRAPE_LOCK:
        state = dict(SCRAPE_STATE)
    try:
        latest = ScrapeRun.objects.filter(status='running').first() or ScrapeRun.objects.first()
        if latest:
            state.update({
                'run_id': latest.pk,
                'status': latest.status,
                'running': latest.status == 'running',
                'message': latest.progress_message or latest.status.title(),
                'error': latest.error,
                'current': latest.progress_current,
                'total': latest.progress_total,
                'new_titles': latest.new_titles,
                'started_at': latest.started_at.isoformat(),
                'finished_at': latest.finished_at.isoformat() if latest.finished_at else None,
                'process_id': latest.process_id,
            })
    except Exception:
        logger.exception('Unable to read scraper status')
    return JsonResponse(state)


@rate_limit('activity', 60, 60)
@csrf_protect
@require_POST
def track_activity(request):
    """Record download and trailer-watch activity from the public site."""
    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    event_type = payload.get('event_type')
    if event_type not in {
        ActivityEvent.DOWNLOAD, ActivityEvent.TRAILER_WATCH,
        ActivityEvent.YOUTUBE_SEARCH, ActivityEvent.YOUTUBE_DOWNLOAD,
    }:
        return JsonResponse({'error': 'Unsupported event type'}, status=400)
    movie_id = str(payload.get('movie_id', '')).strip()
    movie_title = str(payload.get('movie_title', '')).strip()
    if not movie_id:
        return JsonResponse({'error': 'movie_id is required'}, status=400)
    if len(movie_id) > 255 or len(movie_title) > 255:
        return JsonResponse({'error': 'Activity fields are too long'}, status=400)

    ActivityEvent.objects.create(movie_id=movie_id, movie_title=movie_title, event_type=event_type)
    return JsonResponse({'recorded': True})


def about(request):
    """About page"""
    total_movies = count_movies()
    categories = get_categories()
    
    context = {
        'total_movies': total_movies,
        'categories': categories
    }
    return render(request, "about.html", context)


def privacy(request):
    return render(request, 'privacy.html')


def terms(request):
    return render(request, 'terms.html')


def browse(request):
    """Browse movies by category"""
    category = resolve_category_slug(request.GET.get('cat', 'all'))
    search_query = request.GET.get('q', '').strip()[:100]
    year = request.GET.get('year', '').strip()
    media_type = request.GET.get('type', '').strip().lower()
    sort = request.GET.get('sort', 'title').strip().lower()
    
    categories = get_categories()
    
    if Movie.objects.exists():
        queryset = Movie.objects.exclude(category__in={'sport-live', 'sport', 'sports', 'wrestling', 'wrestling-live'})
        if search_query:
            from django.db.models import Q
            queryset = queryset.filter(Q(title__icontains=search_query) | Q(description__icontains=search_query))
            page_title = f'Search: {search_query}'
        if category != 'all':
            category_values = [category]
            category_values.extend(
                legacy for legacy, normalized in LEGACY_CATEGORY_ALIASES.items()
                if normalized == category
            )
            queryset = queryset.filter(category__in=category_values)
            page_title = category.replace('-', ' ').title()
        if year.isdigit():
            queryset = queryset.filter(year=int(year))
        if media_type == 'series':
            queryset = queryset.filter(category__in=['hollywood-tv-series', 'nollywood-tv-series', 'bollywood-tv-series', 'other-foreign-series'])
        elif media_type == 'movie':
            queryset = queryset.exclude(category__in=['hollywood-tv-series', 'nollywood-tv-series', 'bollywood-tv-series', 'other-foreign-series'])
        if sort == 'title':
            queryset = queryset.order_by('title')
        elif sort == 'oldest':
            queryset = queryset.order_by('scraped_at', 'title')
        else:
            queryset = queryset.order_by('-scraped_at', 'title')
        if not search_query and category == 'all':
            page_title = 'All Movies'
        queryset = queryset.values()
        paginator = Paginator(queryset, 52)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        movies = list(page_obj.object_list)
        for movie in movies:
            if movie.get('scraped_at'):
                movie['scraped_at'] = movie['scraped_at'].strftime('%Y-%m-%d %H:%M:%S')
        movies = [movie for movie in movies if movie.get('category') not in {'sport-live', 'sport', 'sports', 'wrestling', 'wrestling-live'}]
        total_movies = paginator.count
    elif search_query:
        movies = search_movies(search_query, limit=24)
        page_title = f'Search: {search_query}'
        paginator = Paginator(movies, 52)
        page_obj = paginator.get_page(request.GET.get('page', 1))
        movies = page_obj.object_list
        total_movies = paginator.count
    elif category == 'all':
        movies = load_movies()
        paginator = Paginator(movies, 52)
        page_obj = paginator.get_page(request.GET.get('page', 1))
        movies = page_obj.object_list
        total_movies = paginator.count
        page_title = 'All Movies'
    else:
        movies = get_movies_by_category(category)
        paginator = Paginator(movies, 52)
        page_obj = paginator.get_page(request.GET.get('page', 1))
        movies = page_obj.object_list
        total_movies = paginator.count
        page_title = category.replace('-', ' ').title()
    
    context = {
        'movies': movies,
        'category': category,
        'categories': categories,
        'page_title': page_title,
        'category_intro': CATEGORY_INTROS.get(category if not search_query else ''),
        'search_query': search_query,
        'year': year,
        'media_type': media_type,
        'sort': sort,
        'total_movies': total_movies,
        'page_obj': page_obj,
    }
    get_token(request)
    return render(request, "browse.html", context)


def saved(request):
    """Render the authenticated user's saved titles."""
    movies = Movie.objects.filter(saved_by__user=request.user).values() if request.user.is_authenticated else []
    context = {
        'movies': list(movies),
        'is_authenticated': request.user.is_authenticated,
    }
    get_token(request)
    return render(request, "saved.html", context)


@rate_limit('register', 5, 300)
@csrf_protect
@require_POST
def register(request):
    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)
    username = str(payload.get('username', '')).strip()
    password = str(payload.get('password', ''))
    if len(username) < 3 or len(username) > 150 or not re.match(r'^[A-Za-z0-9_.@+-]+$', username):
        return JsonResponse({'error': 'Choose a valid username.'}, status=400)
    if len(password) < 8:
        return JsonResponse({'error': 'Password must be at least 8 characters.'}, status=400)
    user_model = get_user_model()
    if user_model.objects.filter(username__iexact=username).exists():
        return JsonResponse({'error': 'That username is already in use.'}, status=409)
    user = user_model.objects.create_user(username=username, password=password)
    login(request, user)
    return JsonResponse({'authenticated': True, 'username': user.get_username()}, status=201)


@rate_limit('login', 10, 300)
@csrf_protect
@require_POST
def account_login(request):
    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)
    user = authenticate(request, username=str(payload.get('username', '')).strip(), password=str(payload.get('password', '')))
    if not user:
        return JsonResponse({'error': 'Invalid username or password.'}, status=400)
    login(request, user)
    return JsonResponse({'authenticated': True, 'username': user.get_username()})


@csrf_protect
@require_POST
def account_logout(request):
    logout(request)
    return JsonResponse({'authenticated': False})


CATEGORY_INTROS = {
    'nollywood-movie': 'Browse Nollywood movies on oentbox: the latest Nigerian cinema from Lagos to London, from Yoruba epics and Igbo dramas to blockbuster premieres. Stream, discover and download the films everyone is talking about.',
    'nollywood-tv-series': 'Binge complete Nollywood TV series and Nigerian telenovelas, from reality-show reunions to original drama series, with every episode organised in one place.',
    'hollywood-movie': 'Watch Hollywood movies on oentbox, from awards contenders and sci-fi adventures to comedies and thrillers, all organised for quick browsing and download.',
    'hollywood-tv-series': 'Complete Hollywood TV series seasons with every episode listed, from prestige dramas to cult favourites and network hits.',
    'bollywood-movie': 'Explore Bollywood and Indian cinema on oentbox: romantic dramas, action spectacles and thrillers from Mumbai and beyond.',
    'bollywood-tv-series': 'Indian streaming originals and series with complete seasons, from crime thrillers to period dramas.',
    'foreign-movie': 'The best of world cinema: Korean thrillers, European dramas, Asian action and festival favourites, hand-picked for oentbox.',
    'other-foreign-series': 'Series from around the world that do not fit one country: Spanish thrillers, Hong Kong action, American network shows and more.',
    'korean-drama': 'Korean dramas (K-dramas) with English subtitles, from romance and revenge thrillers to historical epics and fantasy romance.',
    'chinese-drama': 'Chinese dramas (C-dramas) with English subtitles: wuxia fantasies, modern romances and cultivation adventures.',
    'japanese-drama': 'Japanese dramas and films with English subtitles, from live-action manga adaptations to gritty crime stories.',
    'filipino-drama': 'Filipino teleseryes and Tagalog movies, from primetime romance dramas to independent cinema.',
    'turkish-drama': 'Turkish dramas (dizi) with English subtitles: sweeping family sagas, Ottoman epics and Istanbul romance.',
    'thai-drama': 'Thai dramas (lakorn) with English subtitles, from supernatural romance to school dramas and action.',
    'anime': 'Anime series and movies with English subtitles and audio, from shonen classics to seasonal favourites.',
}


@require_GET
def random_movie(request):
    """Send the visitor to a random title: a simple deep-page discovery link."""
    count = Movie.objects.exclude(category__in=EXCLUDED_CATEGORIES).count()
    if not count:
        return HttpResponseRedirect('/browse.html?cat=all')
    offset = random.randint(0, count - 1)
    movie = (Movie.objects.exclude(category__in=EXCLUDED_CATEGORIES)
             .order_by('id').values('id')[offset:offset + 1].first())
    if not movie:
        return HttpResponseRedirect('/browse.html?cat=all')
    return HttpResponseRedirect(f'/video_detail.html?id={quote(str(movie["id"]))}')


@rate_limit('newsletter', 5, 3600)
@csrf_protect
@require_POST
def newsletter_signup(request):
    """Store a newsletter signup email."""
    try:
        payload = json.loads(request.body or '{}')
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid request.'}, status=400)
    email = (payload.get('email') or '').strip().lower()
    if payload.get('website'):
        return JsonResponse({'ok': True})
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return JsonResponse({'error': 'Enter a valid email address.'}, status=400)
    _, created = NewsletterEmail.objects.get_or_create(email=email)
    return JsonResponse({'ok': True, 'subscribed': created})


@rate_limit('movie-search', 40, 60)
@require_GET
def api_search(request):
    """Live search endpoint powering the header search overlay."""
    query = request.GET.get('q', '').strip()
    if len(query) < 2:
        return JsonResponse({'results': []})
    movies = search_movies(query, limit=8)
    results = [{
        'id': movie['id'],
        'title': movie['title'],
        'year': movie.get('year') or '',
        'category': movie.get('category', ''),
        'thumbnail': poster_url(movie.get('thumbnail') or '', 150),
    } for movie in movies]
    return JsonResponse({'results': results})


@require_GET
def saved_api(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required.'}, status=401)
    return JsonResponse({'movie_ids': list(SavedMovie.objects.filter(user=request.user).values_list('movie_id', flat=True))})


@csrf_protect
@require_POST
def save_movie(request, movie_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required.'}, status=401)
    movie = Movie.objects.filter(pk=movie_id).first()
    if not movie:
        return JsonResponse({'error': 'Movie not found.'}, status=404)
    SavedMovie.objects.get_or_create(user=request.user, movie=movie)
    return JsonResponse({'saved': True, 'movie_id': movie_id})


@csrf_protect
@require_POST
def unsave_movie(request, movie_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentication required.'}, status=401)
    SavedMovie.objects.filter(user=request.user, movie_id=movie_id).delete()
    return JsonResponse({'saved': False, 'movie_id': movie_id})


def _json_ld(payload):
    """Serialize JSON-LD for an inline <script type="application/ld+json"> block.

    json.dumps leaves <, > and & untouched, so scraped titles like
    "</script><script>..." would break out of the tag; escape them.
    """
    return (json.dumps(payload)
            .replace('<', '\\u003c')
            .replace('>', '\\u003e')
            .replace('&', '\\u0026'))


def title_detail(request, slug=None):
    """Movie detail page

    Accepts either ?id=<movie_id> (legacy query form) or /m/<slug> (clean URL).
    The slug IS the movie id, just in the path instead of the query string.
    """
    movie_id = request.GET.get('id') or slug
    
    if movie_id:
        movie = get_movie_by_id(movie_id)
        if movie:
            # Get related movies by category
            related = get_movies_by_category(movie.get('category', ''), limit=6)
            # Remove current movie from related
            related = [m for m in related if m.get('id') != movie_id][:5]
            
            context = {
                'movie': movie,
                'related_movies': related,
                'has_movie': True,
                'canonical_url': request.build_absolute_uri(f'/m/{quote(movie_id)}'),
                'seo_json': _json_ld(build_movie_schema(movie, request)),
            }
            get_token(request)
            return render(request, "video_detail.html", context)
    
    # Unknown or missing ids must never serve a random movie's page:
    # that creates soft-404/duplicate URLs for search engines.
    if not movie_id:
        return HttpResponseRedirect('/')
    return render(request, "video_detail.html", {'has_movie': False}, status=404)
