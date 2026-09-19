from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.models import Group
from django.shortcuts import render
from django.http import FileResponse, HttpResponse, JsonResponse
from django.core.cache import cache
from django.core.paginator import Paginator
from django.middleware.csrf import get_token
from django.views.decorators.http import require_GET
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_protect
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
from .models import ActivityEvent, DownloadJob, Movie, SavedMovie, ScrapeRun
from .movie_data import (
    CATEGORY_LABELS,
    LEGACY_CATEGORY_ALIASES,
    get_featured_movies,
    get_movies_by_category,
    get_movie_by_id,
    get_categories,
    search_movies,
    load_movies
)

LEGACY_CATEGORY_ALIASES = {
    **LEGACY_CATEGORY_ALIASES,
    "nollywood-movies": "nollywood-movie",
    "nollywood-series": "nollywood-tv-series",
    "hollywood-movies": "hollywood-movie",
    "hollywood-series": "hollywood-tv-series",
}

SCRAPE_STATE = {
    'running': False,
    'error': '',
    'message': '',
    'current': 0,
    'total': 0,
}
SCRAPE_LOCK = threading.Lock()
DOWNLOAD_JOBS = {}
DOWNLOAD_JOBS_LOCK = threading.Lock()
logger = logging.getLogger(__name__)


def rate_limit(scope, limit, window):
    def decorator(view):
        def wrapped(request, *args, **kwargs):
            identity = request.user.pk if request.user.is_authenticated else request.META.get('REMOTE_ADDR', 'unknown')
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
    location_name, queries = _youtube_location_profile(request)
    return render(request, "youtube.html", {
        'youtube_location': location_name,
        'youtube_chips': [
            {'label': location_name, 'query': ''},
            *({'label': query, 'query': query} for query in queries[1:]),
        ],
    })


def download_manager(request):
    get_token(request)
    return render(request, 'download_manager.html')


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
    publish_candidates = [video for video in summaries if not video['published']][:12]

    def resolve_publish_time(video):
        try:
            detail_options = {'quiet': True, 'no_warnings': True, 'skip_download': True}
            with yt_dlp.YoutubeDL(detail_options) as downloader:
                info = downloader.extract_info(video['url'], download=False)
            return video, _relative_publish_time(info)
        except Exception as error:
            logger.debug('YouTube publish date lookup failed: %s', error)
            return video, ''

    with ThreadPoolExecutor(max_workers=6) as executor:
        for video, published in executor.map(resolve_publish_time, publish_candidates):
            video['published'] = published

    missing_avatars = [
        video for video in summaries
        if not video['channel_thumbnail'] and (video['channel_url'] or video['channel_id'])
    ]
    with ThreadPoolExecutor(max_workers=8) as executor:
        thumbnails = executor.map(
            lambda video: _channel_thumbnail(video['channel_url'], video['channel_id']),
            missing_avatars,
        )
        for video, thumbnail in zip(missing_avatars, thumbnails):
            video['channel_thumbnail'] = thumbnail
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
        limit = int(request.GET.get('limit', 50))
    except ValueError:
        limit = 50
    limit = max(6, min(limit, 100))
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
    video_id = request.GET.get('id', '').strip()
    if not YOUTUBE_ID_RE.match(video_id):
        return render(request, 'youtube_detail.html', {'error': 'This video could not be found.'}, status=404)
    video_url = f'https://www.youtube.com/watch?v={video_id}'
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
        similar = _youtube_search(info.get('channel') or info.get('title') or 'YouTube', limit=6)
        similar = [item for item in similar if item['id'] != video_id]
        for item in similar:
            if not item['channel_thumbnail']:
                item['channel_thumbnail'] = _channel_thumbnail(item['channel_url'], item['channel_id'])
        return render(request, 'youtube_detail.html', {
            'video': video,
            'comments': comments,
            'similar_videos': similar,
            'canonical_url': request.build_absolute_uri(f'/youtube/video.html?id={quote(video_id)}'),
            'seo_json': json.dumps({
                '@context': 'https://schema.org',
                '@type': 'VideoObject',
                'name': video['title'],
                'description': video['description'][:500] or video['title'],
                'thumbnailUrl': video['thumbnail'],
                'uploadDate': info.get('upload_date') or '',
                'contentUrl': video_url,
                'embedUrl': f'https://www.youtube.com/embed/{video_id}',
            }),
        })
    except Exception as error:
        logger.warning('YouTube detail failed: %s', error)
        return render(request, 'youtube_detail.html', {'error': 'Video details are temporarily unavailable.'}, status=502)


def _set_download_job(job_id, **updates):
    with DOWNLOAD_JOBS_LOCK:
        if job_id in DOWNLOAD_JOBS:
            DOWNLOAD_JOBS[job_id].update(updates)
    persisted_fields = {
        key: value for key, value in updates.items()
        if key in {
            'status', 'progress', 'detail', 'filename', 'path', 'output_dir',
            'downloaded_bytes', 'total_bytes', 'speed', 'eta',
            'stop_requested', 'cancel_requested',
        }
    }
    if persisted_fields:
        DownloadJob.objects.filter(pk=job_id).update(**persisted_fields)


def _ensure_download_session(request):
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def _owned_download_job(request, job_id):
    job = DownloadJob.objects.filter(pk=job_id).first()
    if not job:
        return None
    if request.user.is_authenticated and job.user_id == request.user.pk:
        return job
    if not request.user.is_authenticated and job.user_id is None and job.session_key == request.session.session_key:
        return job
    return None


class _DownloadPaused(Exception):
    """Raised inside the yt-dlp progress hook to unwind cleanly on pause/cancel."""


def _run_youtube_download(job_id):
    with DOWNLOAD_JOBS_LOCK:
        job = DOWNLOAD_JOBS.get(job_id)
    if not job:
        persisted = DownloadJob.objects.filter(pk=job_id).first()
        if not persisted:
            return
        selected_format, extension = YOUTUBE_DOWNLOAD_FORMATS.get(
            persisted.download_format, YOUTUBE_DOWNLOAD_FORMATS['video'],
        )
        job = {
            'status': persisted.status,
            'progress': persisted.progress,
            'detail': persisted.detail,
            'video_url': persisted.video_url,
            'download_format': persisted.download_format,
            'selected_format': selected_format,
            'extension': extension,
            'output_dir': persisted.output_dir,
            'stop_requested': persisted.stop_requested,
            'cancel_requested': persisted.cancel_requested,
        }
        with DOWNLOAD_JOBS_LOCK:
            DOWNLOAD_JOBS[job_id] = job
    output_dir = Path(job['output_dir'])
    video_url = job['video_url']
    download_format = job['download_format']
    selected_format = job['selected_format']
    extension = job['extension']
    output_template = str(output_dir / '%(title).120s.%(ext)s')
    initial_state = DownloadJob.objects.filter(pk=job_id).values(
        'stop_requested', 'cancel_requested',
    ).first()
    if initial_state and initial_state['cancel_requested']:
        _cleanup_download_dir(output_dir)
        _set_download_job(job_id, status='error', detail='Download cancelled.')
        return
    if initial_state and initial_state['stop_requested']:
        _set_download_job(job_id, status='paused', detail='Paused')
        return
    _set_download_job(job_id, status='downloading', detail='Downloading...', stop_requested=False)

    def progress_hook(data):
        with DOWNLOAD_JOBS_LOCK:
            current = DOWNLOAD_JOBS.get(job_id)
            stop_requested = bool(current and current.get('stop_requested'))
        persisted = DownloadJob.objects.filter(pk=job_id).values(
            'stop_requested', 'cancel_requested',
        ).first()
        stop_requested = stop_requested or bool(persisted and persisted['stop_requested'])
        if stop_requested:
            raise _DownloadPaused()
        if data.get('status') == 'downloading':
            total = data.get('total_bytes') or data.get('total_bytes_estimate') or 0
            downloaded = data.get('downloaded_bytes') or 0
            percent = min(99, round(downloaded * 100 / total)) if total else 0
            _set_download_job(job_id, status='downloading', progress=percent,
                               detail=f'Downloading... {percent}%' if total else 'Downloading...',
                               downloaded_bytes=downloaded, total_bytes=total,
                               speed=data.get('speed') or 0, eta=data.get('eta'))
        elif data.get('status') == 'finished':
            _set_download_job(job_id, progress=99, detail='Finalizing file...')

    try:
        import yt_dlp

        options = {
            'quiet': True,
            'no_warnings': True,
            'format': selected_format,
            'noplaylist': True,
            'retries': 3,
            'fragment_retries': 3,
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web_safari', 'tv'],
                },
            },
            'progress_hooks': [progress_hook],
            'postprocessors': ([{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }] if download_format == 'audio_mp3' else []),
            'outtmpl': output_template,
            'continuedl': True,
            'nopart': False,
        }
        if download_format.startswith('video'):
            options['merge_output_format'] = 'mp4'
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(video_url, download=True)
        files = [file for file in output_dir.iterdir() if file.is_file() and not file.name.endswith('.part')]
        if not files:
            raise RuntimeError('No downloaded file was produced.')
        filename = get_valid_filename(info.get('title') or 'youtube-video')
        filename = f'{filename[:120]}.{extension}'
        _set_download_job(job_id, status='complete', progress=100, detail='Download ready.',
                           path=str(files[0]), filename=filename)
        ActivityEvent.objects.create(
            movie_id=video_url,
            movie_title=info.get('title') or 'YouTube video',
            event_type=ActivityEvent.YOUTUBE_DOWNLOAD,
        )
    except _DownloadPaused:
        persisted = DownloadJob.objects.filter(pk=job_id).values('cancel_requested').first()
        with DOWNLOAD_JOBS_LOCK:
            current = DOWNLOAD_JOBS.get(job_id)
            cancelled = bool(current and current.get('cancel_requested')) or bool(persisted and persisted['cancel_requested'])
        if cancelled:
            _cleanup_download_dir(output_dir)
            _set_download_job(job_id, status='error', progress=0, detail='Download cancelled.',
                               stop_requested=False, cancel_requested=False)
            with DOWNLOAD_JOBS_LOCK:
                DOWNLOAD_JOBS.pop(job_id, None)
        else:
            _set_download_job(job_id, status='paused', detail='Paused', stop_requested=False)
    except Exception as error:
        logger.warning('YouTube download failed: %s', error)
        with DOWNLOAD_JOBS_LOCK:
            current = DOWNLOAD_JOBS.get(job_id)
            cancelled = bool(current and current.get('cancel_requested'))
        _cleanup_download_dir(output_dir)
        if cancelled:
            with DOWNLOAD_JOBS_LOCK:
                DOWNLOAD_JOBS.pop(job_id, None)
        else:
            unavailable = 'not available' in str(error).lower() or 'unavailable' in str(error).lower()
            detail = 'This YouTube video is unavailable.' if unavailable else 'Download failed. Please try again.'
            _set_download_job(job_id, status='error', progress=0, detail=detail)


def _cleanup_download_dir(output_dir):
    try:
        for file in output_dir.glob('*'):
            file.unlink(missing_ok=True)
        output_dir.rmdir()
    except OSError:
        pass


def _spawn_download_job(job_id):
    import subprocess
    import sys

    if os.environ.get('QUEUE_BACKEND', '').lower() == 'celery':
        from .tasks import run_download_job_task
        run_download_job_task.delay(job_id)
        return None

    return subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve().parent.parent / 'manage.py'),
         'run_download_job', '--job-id', job_id],
        cwd=str(Path(__file__).resolve().parent.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )


YOUTUBE_DOWNLOAD_FORMATS = {
    'video': ('bestvideo*+bestaudio/bestvideo*/best', 'mp4'),
    'video_720': ('bestvideo*[height<=720]+bestaudio/best[height<=720]/best', 'mp4'),
    'video_480': ('bestvideo*[height<=480]+bestaudio/best[height<=480]/best', 'mp4'),
    'audio': ('bestaudio/best', 'm4a'),
    'audio_mp3': ('bestaudio/best', 'mp3'),
}


@rate_limit('youtube-download', 10, 60)
@csrf_protect
@require_POST
def youtube_download(request):
    try:
        payload = json.loads(request.body or '{}')
        video_url = str(payload.get('url', '')).strip()
        download_format = str(payload.get('format', 'video')).strip().lower()
        parsed = urlparse(video_url)
        if parsed.scheme not in {'http', 'https'} or (parsed.hostname or '').lower() not in YOUTUBE_HOSTS:
            return JsonResponse({'error': 'Only YouTube video URLs are supported.'}, status=400)
        if download_format not in YOUTUBE_DOWNLOAD_FORMATS:
            return JsonResponse({'error': 'Unsupported download format.'}, status=400)
        selected_format, extension = YOUTUBE_DOWNLOAD_FORMATS[download_format]

        job_id = uuid.uuid4().hex
        output_dir = Path(tempfile.mkdtemp(prefix='oentbox-youtube-'))
        session_key = '' if request.user.is_authenticated else _ensure_download_session(request)
        DownloadJob.objects.create(
            id=job_id,
            user=request.user if request.user.is_authenticated else None,
            session_key=session_key,
            video_url=video_url,
            download_format=download_format,
            status='starting',
            detail='Preparing download...',
            output_dir=str(output_dir),
        )
        with DOWNLOAD_JOBS_LOCK:
            DOWNLOAD_JOBS[job_id] = {
                'status': 'starting', 'progress': 0, 'detail': 'Preparing download...',
                'video_url': video_url, 'download_format': download_format,
                'selected_format': selected_format, 'extension': extension,
                'output_dir': str(output_dir), 'stop_requested': False, 'cancel_requested': False,
            }
        try:
            _spawn_download_job(job_id)
        except Exception:
            DownloadJob.objects.filter(pk=job_id).update(
                status='error', detail='The download worker could not start.',
            )
            _cleanup_download_dir(output_dir)
            raise
        return JsonResponse({'job_id': job_id})
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON.'}, status=400)
    except Exception:
        logger.exception('Could not create YouTube download job')
        return JsonResponse({'error': 'Could not start the download. Please try again.'}, status=503)


@require_GET
def youtube_download_direct(request):
    """Download a YouTube file directly through the browser response."""
    video_url = request.GET.get('url', '').strip()
    download_format = request.GET.get('format', 'video').strip().lower()
    parsed = urlparse(video_url)
    if parsed.scheme not in {'http', 'https'} or (parsed.hostname or '').lower() not in YOUTUBE_HOSTS:
        return JsonResponse({'error': 'Only YouTube video URLs are supported.'}, status=400)
    if download_format not in YOUTUBE_DOWNLOAD_FORMATS:
        return JsonResponse({'error': 'Unsupported download format.'}, status=400)

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


DOWNLOAD_MIME_TYPES = {
    'mp4': 'video/mp4',
    'm4a': 'audio/mp4',
    'mp3': 'audio/mpeg',
    'webm': 'video/webm',
    'mkv': 'video/x-matroska',
}


def _mime_for_filename(filename):
    if not filename:
        return 'application/octet-stream'
    suffix = Path(filename).suffix.lstrip('.').lower()
    return DOWNLOAD_MIME_TYPES.get(suffix, 'application/octet-stream')


@require_GET
def youtube_download_status(request, job_id):
    persisted = _owned_download_job(request, job_id)
    if not persisted:
        return JsonResponse({'error': 'Download job not found.'}, status=404)
    if persisted.status == 'starting' and (timezone.now() - persisted.updated_at).total_seconds() > 120:
        persisted.status = 'error'
        persisted.detail = 'The download worker did not start. Please retry.'
        persisted.save(update_fields=('status', 'detail', 'updated_at'))
    file_size = persisted.total_bytes if persisted.status == 'complete' else 0
    if persisted.status == 'complete' and persisted.path:
        try:
            file_size = Path(persisted.path).stat().st_size
        except OSError:
            file_size = 0
    return JsonResponse({
        'status': persisted.status,
        'progress': persisted.progress,
        'detail': persisted.detail,
        'downloaded_bytes': persisted.downloaded_bytes,
        'total_bytes': persisted.total_bytes,
        'speed': persisted.speed,
        'eta': persisted.eta,
        'filename': persisted.filename,
        'mime_type': _mime_for_filename(persisted.filename),
        'file_size': file_size,
    })


@rate_limit('download-control', 30, 60)
@csrf_protect
@require_POST
def youtube_download_pause(request, job_id):
    persisted = _owned_download_job(request, job_id)
    if not persisted:
        return JsonResponse({'error': 'Download job not found.'}, status=404)
    with DOWNLOAD_JOBS_LOCK:
        job = DOWNLOAD_JOBS.get(job_id)
        current_status = persisted.status
        if current_status not in {'starting', 'downloading'}:
            return JsonResponse({'error': 'Download cannot be paused right now.'}, status=409)
        if job:
            job['stop_requested'] = True
            job['status'] = 'pausing'
            job['detail'] = 'Pausing...'
    _set_download_job(job_id, stop_requested=True, status='pausing', detail='Pausing...')
    return JsonResponse({'status': 'pausing'})


@rate_limit('download-control', 30, 60)
@csrf_protect
@require_POST
def youtube_download_resume(request, job_id):
    persisted = _owned_download_job(request, job_id)
    if not persisted:
        return JsonResponse({'error': 'Download job not found.'}, status=404)
    with DOWNLOAD_JOBS_LOCK:
        job = DOWNLOAD_JOBS.get(job_id)
        current_status = persisted.status
        if current_status != 'paused':
            return JsonResponse({'error': 'Download is not paused.'}, status=409)
        if job:
            job['status'] = 'starting'
            job['stop_requested'] = False
            job['detail'] = 'Resuming...'
    _set_download_job(job_id, status='starting', stop_requested=False, cancel_requested=False, detail='Resuming...')
    try:
        _spawn_download_job(job_id)
    except OSError:
        _set_download_job(job_id, status='paused', detail='Resume could not be started.')
        return JsonResponse({'error': 'Resume could not be started.'}, status=503)
    return JsonResponse({'status': 'starting'})


@rate_limit('download-control', 30, 60)
@csrf_protect
@require_POST
def youtube_download_cancel(request, job_id):
    persisted = _owned_download_job(request, job_id)
    if not persisted:
        return JsonResponse({'error': 'Download job not found.'}, status=404)
    with DOWNLOAD_JOBS_LOCK:
        job = DOWNLOAD_JOBS.get(job_id)
        active = (job and job.get('status') in {'starting', 'downloading', 'pausing'}) or persisted.status in {'starting', 'downloading', 'pausing', 'cancelling'}
        if active:
            if job:
                job['cancel_requested'] = True
                job['stop_requested'] = True
                job['status'] = 'cancelling'
                job['detail'] = 'Cancelling...'
            active_cancel = True
        else:
            active_cancel = False
            output_dir = job.get('output_dir') if job else persisted.output_dir
            path = job.get('path') if job else persisted.path
            DOWNLOAD_JOBS.pop(job_id, None)
    if active_cancel:
        _set_download_job(job_id, cancel_requested=True, stop_requested=True, status='cancelling', detail='Cancelling...')
        return JsonResponse({'status': 'cancelling'})
    if path:
        Path(path).unlink(missing_ok=True)
    if output_dir:
        _cleanup_download_dir(Path(output_dir))
    return JsonResponse({'status': 'cancelled'})


@require_GET
def youtube_download_file(request, job_id):
    """Stream the downloaded file to the client.

    Improvements over the previous version:
      * Validates the file still exists on disk before opening it.
      * Sends ``Content-Length`` so the browser/UI shows the *actual* file size.
      * Sends ``Accept-Ranges: bytes`` and honors ``Range`` requests so the
        file can be resumed if the connection drops mid-download — exactly
        what "advanced downloaders" need.
      * Sets the proper ``Content-Type`` per extension (video/mp4, audio/mpeg,
        ...) instead of relying on the browser's sniffing.
      * Does NOT delete the file when the response finishes — the existing
        ``cleanup_downloads`` management command (TTL based) handles that, so
        a user can retry / re-save a file without getting a 404 JSON blob.
    """
    persisted = _owned_download_job(request, job_id)
    if not persisted:
        return JsonResponse({'error': 'Download job not found.'}, status=404)
    with DOWNLOAD_JOBS_LOCK:
        job = DOWNLOAD_JOBS.get(job_id)
    if persisted.status == 'complete':
        job = {
            'status': 'complete',
            'path': persisted.path or (job.get('path') if job else ''),
            'filename': persisted.filename or (job.get('filename') if job else ''),
        }
    if not job or job.get('status') != 'complete' or not job.get('path'):
        return JsonResponse({'error': 'Download is not ready.'}, status=409)

    file_path = Path(job['path'])
    if not file_path.exists() or not file_path.is_file():
        # File was already cleaned up by the TTL command. Mark the job so the
        # UI can show an actionable error and let the user retry from scratch.
        _set_download_job(job_id, status='error', detail='File expired. Please restart the download.')
        return JsonResponse({'error': 'File expired. Please restart the download.'}, status=410)

    file_size = file_path.stat().st_size
    filename = job.get('filename') or persisted.filename or file_path.name
    content_type = _mime_for_filename(filename)

    # --- Range request handling -------------------------------------------------
    range_header = request.META.get('HTTP_RANGE')
    start = 0
    end = file_size - 1
    partial = False
    if range_header and 'bytes=' in range_header:
        try:
            range_spec = range_header.split('bytes=', 1)[1].split('-', 1)
            start = int(range_spec[0]) if range_spec[0] else 0
            end = int(range_spec[1]) if range_spec[1] else file_size - 1
            if start > end or start >= file_size:
                response = HttpResponse(status=416)
                response['Content-Range'] = f'bytes */{file_size}'
                return response
            end = min(end, file_size - 1)
            partial = True
        except (ValueError, IndexError):
            start, end, partial = 0, file_size - 1, False

    content_length = end - start + 1
    file_handle = open(file_path, 'rb')
    if start:
        file_handle.seek(start)

    response = FileResponse(file_handle, content_type=content_type)
    response['Content-Length'] = str(content_length)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['Accept-Ranges'] = 'bytes'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    if partial:
        response.status_code = 206
        response['Content-Range'] = f'bytes {start}-{end}/{file_size}'
    return response


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
            for event in ActivityEvent.objects.all()
        ],
        'admin_user_count': user_model.objects.count(),
        'admin_staff_count': user_model.objects.filter(is_staff=True).count(),
        'admin_group_count': Group.objects.count(),
        'admin_active_count': user_model.objects.filter(is_active=True).count(),
        'admin_recent_users': user_model.objects.order_by('-date_joined')[:5],
    }
    return render(request, "dashboard.html", context)


def dashboard_titles():
    result = []
    for movie in load_movies():
        video_info = movie.get('video_info') or {}
        result.append({
            'id': movie.get('id', ''), 'title': movie.get('title', ''),
            'category': movie.get('category', 'unknown'),
            'type': video_info.get('Type') or ('TV Series' if movie.get('category') == 'tv-series' else 'Movie'),
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
            for event in ActivityEvent.objects.all()
        ],
        'scraper': state,
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

    started_count = len(load_movies())
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
    total_movies = len(load_movies())
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
            queryset = queryset.filter(category=category)
            page_title = category.replace('-', ' ').title()
        if year.isdigit():
            queryset = queryset.filter(year=int(year))
        if media_type == 'series':
            queryset = queryset.filter(category='tv-series')
        elif media_type == 'movie':
            queryset = queryset.exclude(category='tv-series')
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


@require_GET
def saved_api(request):
    if not request.user.is_authenticated:
        return JsonResponse({'movie_ids': []})
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


def title_detail(request):
    """Movie detail page"""
    movie_id = request.GET.get('id')
    
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
                'canonical_url': request.build_absolute_uri(f'/video_detail.html?id={quote(movie_id)}'),
                'seo_json': json.dumps({
                    '@context': 'https://schema.org',
                    '@type': 'Movie',
                    'name': movie.get('title', ''),
                    'description': movie.get('description', '')[:500],
                    'image': movie.get('thumbnail', ''),
                    'dateCreated': str(movie.get('year') or ''),
                }),
            }
            get_token(request)
            return render(request, "video_detail.html", context)
    
    # Fallback: show first featured movie
    movies = get_featured_movies(limit=1)
    if movies:
        context = {
            'movie': movies[0],
            'related_movies': get_featured_movies(limit=5)[1:6],
            'has_movie': True
        }
    else:
        context = {'has_movie': False}
    
    get_token(request)
    return render(request, "video_detail.html", context)
