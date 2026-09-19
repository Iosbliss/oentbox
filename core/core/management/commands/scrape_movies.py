import requests
import json
import re
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.utils import timezone
from core.models import Movie
from core.movie_data import classify_movie_category
import os
import time
import random
import tempfile
from datetime import datetime


PROGRESS_CALLBACK = None

# Categories that should never appear on the website. Any scraped movie
# whose category matches one of these values is dropped before it is saved
# to disk or to the database. The list also acts as a defensive guard for
# legacy catalog entries (e.g. `sport-live`, `wrestling`) that earlier
# scraper versions emitted.
EXCLUDED_CATEGORIES = {'sport-live', 'sport', 'sports', 'wrestling', 'wrestling-live'}


def set_progress_callback(callback):
    global PROGRESS_CALLBACK
    PROGRESS_CALLBACK = callback


class Command(BaseCommand):
    help = 'Scrape movies from 9jarocks.net and save to JSON'
    # Match movie detail URLs like /videodownload/<slug>-id<digits>.html.
    # The trailing `$` was relaxed because this regex is sometimes applied to
    # raw HTML fragments where the URL is followed by `"` or `>`, which would
    # make the anchor fail to match. The character class excludes `<`, `>`,
    # `"`, and whitespace so the URL cannot run past its closing tag.
    MOVIE_LINK_RE = re.compile(
        r'/videodownload/(?!category/)[^"\s<>]+-id\d+\.html(?:[?#][^"\s<>]*)?',
        re.IGNORECASE,
    )
    VIDEO_INFO_LABELS = [
        'Filename',
        'Filesize',
        'Duration',
        'Imdb',
        'Title',
        'Year',
        'Type',
        'Country',
        'Language',
        'Director',
        'Genre',
        'Stars',
        'Total Episodes',
        'Status',
        'Subtitle',
    ]

    def report_progress(self, message, current=0, total=0):
        if PROGRESS_CALLBACK:
            try:
                PROGRESS_CALLBACK(message, current, total)
            except Exception:
                pass

    def add_arguments(self, parser):
        parser.add_argument(
            '--pages',
            type=int,
            default=None,
            help='Number of pages to scrape. Omit this and use --auto to stop when no more movie pages are found.'
        )
        parser.add_argument(
            '--auto',
            action='store_true',
            help='Keep scraping until the sitemap and category archives are exhausted.'
        )
        parser.add_argument(
            '--max-pages',
            type=int,
            default=500,
            help='Per-category page cap in --auto mode (default: 500).'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=0,
            help='Max new movie records to add this run. 0 means no limit.'
        )
        parser.add_argument(
            '--output',
            type=str,
            default='scraper/movies.json',
            help='Output JSON file path'
        )

    def handle(self, *args, **options):
        pages = options['pages']
        auto_mode = options['auto']
        max_pages = options['max_pages']
        record_limit = options['limit']
        output_file = options['output']
        output_path = os.path.join(settings.BASE_DIR, output_file)

        if auto_mode and pages is not None:
            self.stdout.write(self.style.WARNING('Both --auto and --pages were provided. Using --auto mode.'))
            pages = None
        if not auto_mode and pages is None:
            pages = 3

        if auto_mode:
            self.report_progress('Discovering sitemap and category archives...')
            self.stdout.write(
                self.style.SUCCESS(
                    'Starting auto-scrape from 9jarocks.net using sitemaps and category archives...'
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS(f'Starting to scrape {pages} homepage listing page(s)...'))

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        session = requests.Session()
        session.headers.update(headers)

        existing_movies = self.load_existing_movies(output_path)
        existing_movies = [movie for movie in existing_movies if self.is_movie_link(movie.get('link', ''))]
        all_movies = []
        seen_links = {self.normalize_movie_link(movie.get('link', '')) for movie in existing_movies if movie.get('link')}
        added_this_run = 0

        def can_add_more():
            return record_limit <= 0 or added_this_run < record_limit

        def add_movie(movie):
            nonlocal added_this_run
            if not movie:
                return False
            link = self.normalize_movie_link(movie.get('link', ''))
            if not link or not self.is_movie_link(link) or link in seen_links:
                return False
            if not can_add_more():
                return False
            movie['link'] = link
            all_movies.append(movie)
            seen_links.add(link)
            added_this_run += 1
            if added_this_run % 25 == 0:
                self.write_catalog(output_path, existing_movies, all_movies)
                self.stdout.write(self.style.SUCCESS(f'Checkpoint: {added_this_run} new movies saved.'))
            return True

        homepage_pages = 1 if auto_mode else pages
        for page in range(1, homepage_pages + 1):
            path = f'/page/{page}' if page > 1 else '/'
            try:
                self.report_progress(f'Scraping homepage listing {page} of {homepage_pages}', page, homepage_pages)
                self.stdout.write(f'Scraping homepage listing {page}: https://9jarocks.net{path}')
                response = self.fetch_page(session, path)
                soup = BeautifulSoup(response.content, 'html.parser')
                articles = self.extract_articles(soup)
                self.stdout.write(f'Found {len(articles)} movie links on homepage listing {page}')
                for article in articles:
                    if not can_add_more():
                        break
                    link = self.normalize_movie_link(article.get('link', '') if isinstance(article, dict) else '')
                    if link and link in seen_links:
                        continue
                    add_movie(self.parse_article(article, soup, session))
                    time.sleep(random.uniform(0.2, 0.6))
            except Exception as error:
                self.stdout.write(self.style.ERROR(f'Error processing homepage listing {page}: {error}'))
            time.sleep(random.uniform(1, 2))

        if auto_mode and can_add_more():
            sitemap_links = self.discover_sitemap_movie_links(session)
            pending = [link for link in sitemap_links if self.normalize_movie_link(link) not in seen_links]
            if record_limit > 0:
                pending = pending[: max(0, record_limit - added_this_run)]
            self.stdout.write(self.style.SUCCESS(f'Sitemap discovered {len(sitemap_links)} movie URLs; {len(pending)} are new.'))
            for index, link in enumerate(pending, start=1):
                if not can_add_more():
                    break
                self.report_progress(f'Scraping sitemap movies ({index}/{len(pending)})', index, len(pending))
                add_movie(self.parse_article({'link': link, 'title': ''}, None, session))
                if index % 20 == 0:
                    self.stdout.write(f'Sitemap progress: {index}/{len(pending)}')
                time.sleep(random.uniform(0.25, 0.7))

        if auto_mode and can_add_more():
            self.scrape_category_archives(session, add_movie, seen_links, max_pages, can_add_more)

        if not all_movies and not existing_movies:
            raise CommandError('Scrape failed without producing movie records.')

        if not all_movies:
            self.stdout.write(self.style.WARNING('No new movies found; existing catalog was preserved.'))
            self.write_catalog(output_path, existing_movies, all_movies)
            return

        merged_movies = self.write_catalog(output_path, existing_movies, all_movies)
        self.stdout.write(self.style.SUCCESS(f'Scraped {len(all_movies)} new movies this run.'))
        self.stdout.write(self.style.SUCCESS(f'Catalog now contains {len(merged_movies)} movies.'))
        self.stdout.write(self.style.SUCCESS(f'Data saved to: {output_path}'))

        categories = {}
        for movie in merged_movies:
            cat = movie.get('category', 'unknown')
            categories[cat] = categories.get(cat, 0) + 1

        self.stdout.write(self.style.NOTICE('\nMovies by category:'))
        for cat, count in sorted(categories.items()):
            self.stdout.write(f'  {cat}: {count}')

    def fetch_page(self, session, path):
        """Fetch a listing page with retries and a www-host fallback."""
        hosts = ['https://9jarocks.net', 'https://www.9jarocks.net']
        last_error = None
        for host in hosts:
            for attempt in range(3):
                try:
                    response = session.get(f'{host}{path}', timeout=30)
                    response.raise_for_status()
                    return response
                except requests.RequestException as error:
                    last_error = error
                    if attempt < 2:
                        time.sleep(2 ** attempt)
        raise last_error

    def load_existing_movies(self, output_path):
        if not os.path.exists(output_path):
            return []
        try:
            with open(output_path, 'r', encoding='utf-8') as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError):
            return []

    def write_catalog(self, output_path, existing_movies, new_movies):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        merged_movies = []
        seen_keys = set()
        for movie in existing_movies + new_movies:
            # Drop any movie whose category is on the excluded list (e.g.
            # sport-live) so legacy catalog entries are purged on the next
            # scrape run, not just blocked at render time.
            if movie.get('category') in EXCLUDED_CATEGORIES:
                continue
            link = self.normalize_movie_link(movie.get('link', ''))
            if not self.is_movie_link(link):
                continue
            movie['link'] = link
            key = link or movie.get('id')
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            merged_movies.append(movie)
        output_directory = os.path.dirname(output_path) or '.'
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=output_directory, delete=False) as handle:
            json.dump(merged_movies, handle, indent=2, ensure_ascii=False)
            temporary_path = handle.name
        os.replace(temporary_path, output_path)
        # Purge any excluded-category rows (e.g. sport-live) that may have
        # been persisted by an earlier scraper run. This keeps the database
        # in sync with the cleaned JSON catalog.
        Movie.objects.filter(category__in=EXCLUDED_CATEGORIES).delete()
        for movie in merged_movies:
            scraped_at = movie.get('scraped_at')
            try:
                scraped_at = timezone.make_aware(
                    datetime.strptime(scraped_at, '%Y-%m-%d %H:%M:%S'),
                    timezone.get_default_timezone(),
                )
            except (TypeError, ValueError):
                scraped_at = timezone.now()
            Movie.objects.update_or_create(
                id=str(movie.get('id', ''))[:255],
                defaults={
                    'title': str(movie.get('title', ''))[:500],
                    'description': movie.get('description', ''),
                    'thumbnail': movie.get('thumbnail', ''),
                    'link': movie.get('link', ''),
                    'year': movie.get('year'),
                    'category': movie.get('category', 'unknown'),
                    'source': movie.get('source', '9jarocks'),
                    'scraped_at': scraped_at,
                    'video_info': movie.get('video_info') or {},
                    'trailer_url': movie.get('trailer_url', ''),
                    'trailer_embed_url': movie.get('trailer_embed_url', ''),
                    'trailer_title': movie.get('trailer_title', ''),
                    'download_links': movie.get('download_links') or [],
                    'download_help_url': movie.get('download_help_url', ''),
                    'screenshots': movie.get('screenshots') or [],
                },
            )
        return merged_movies

    def is_movie_link(self, url):
        if not url:
            return False
        path = urlparse(url).path.lower()
        if '/category/' in path or 'how-to-download' in path:
            return False
        if re.search(r'/videodownload/video-', path):
            return False
        return bool(self.MOVIE_LINK_RE.search(path))

    def normalize_movie_link(self, url):
        if not url:
            return ''
        parsed = urlparse(url)
        path = parsed.path or url
        if parsed.scheme and parsed.netloc:
            return f'https://9jarocks.net{parsed.path}'
        if path.startswith('/'):
            return f'https://9jarocks.net{path}'
        return url.split('?')[0].split('#')[0]

    def discover_sitemap_movie_links(self, session):
        """Collect every movie URL listed in the WordPress post sitemaps."""
        links = []
        seen = set()
        try:
            index = session.get('https://9jarocks.net/wp-sitemap.xml', timeout=30)
            index.raise_for_status()
        except requests.RequestException as error:
            self.stdout.write(self.style.WARNING(f'Could not load sitemap index: {error}'))
            return links

        sitemap_urls = re.findall(r'<loc>\s*(.*?)\s*</loc>', index.text)
        post_sitemaps = [url for url in sitemap_urls if 'wp-sitemap-posts-post-' in url]
        self.stdout.write(f'Found {len(post_sitemaps)} post sitemaps')

        for sitemap_url in post_sitemaps:
            try:
                response = session.get(sitemap_url, timeout=30)
                response.raise_for_status()
            except requests.RequestException as error:
                self.stdout.write(self.style.WARNING(f'Sitemap failed {sitemap_url}: {error}'))
                continue
            for loc in re.findall(r'<loc>\s*(.*?)\s*</loc>', response.text):
                link = self.normalize_movie_link(loc)
                if self.is_movie_link(link) and link not in seen:
                    seen.add(link)
                    links.append(link)
            time.sleep(random.uniform(0.4, 1.0))
        return links

    def extract_last_page(self, html, category_path):
        pages = [
            int(value)
            for value in re.findall(rf'{re.escape(category_path)}/page/(\d+)', html, flags=re.IGNORECASE)
        ]
        return max(pages) if pages else 1

    def scrape_category_archives(self, session, add_movie, seen_links, max_pages, can_add_more):
        """Crawl category archives using their real numbered pagination."""
        try:
            homepage = self.fetch_page(session, '/').content
            soup = BeautifulSoup(homepage, 'html.parser')
        except requests.RequestException as error:
            self.stdout.write(self.style.WARNING(f'Could not discover category archives: {error}'))
            return

        category_paths = set()
        for link in soup.find_all('a', href=re.compile(r'/category/videodownload/[^?#]+', re.IGNORECASE)):
            href = link.get('href', '')
            path = urlparse(href).path if href.startswith('http') else href
            if path and '/page/' not in path:
                category_paths.add(path.rstrip('/'))

        for category_path in sorted(category_paths):
            if not can_add_more():
                return
            # Skip sport- and wrestling-related category archives (e.g.
            # /category/videodownload/sport-live or /category/videodownload/wrestling)
            # so the catalog never re-absorbs that content from the source site.
            lowered = category_path.lower()
            if 'sport' in lowered or 'wrestling' in lowered:
                self.stdout.write(self.style.NOTICE(f'Skipping excluded category archive: {category_path}'))
                continue
            empty_pages = 0
            last_page = 1
            page = 1
            while page <= max(last_page, 1) and page <= max_pages:
                path = category_path if page == 1 else f'{category_path}/page/{page}'
                try:
                    self.report_progress(f'Scraping category {category_path} page {page}', page, last_page)
                    response = self.fetch_page(session, path)
                    page_soup = BeautifulSoup(response.content, 'html.parser')
                    if page == 1:
                        last_page = min(self.extract_last_page(response.text, category_path), max_pages)
                        self.stdout.write(f'Category {category_path} has {last_page} listing page(s)')
                    articles = self.extract_articles(page_soup)
                except requests.RequestException as error:
                    self.stdout.write(self.style.WARNING(f'Category page failed {path}: {error}'))
                    empty_pages += 1
                    if empty_pages >= 3:
                        break
                    page += 1
                    continue

                added = 0
                movie_links = 0
                for article in articles:
                    if not can_add_more():
                        return
                    link = article.get('link') if isinstance(article, dict) else ''
                    if self.is_movie_link(link):
                        movie_links += 1
                    if link and self.normalize_movie_link(link) in seen_links:
                        continue
                    if add_movie(self.parse_article(article, page_soup, session)):
                        added += 1
                    time.sleep(random.uniform(0.2, 0.6))

                self.stdout.write(
                    f'Category {category_path} page {page}/{last_page}: {movie_links} movie links, {added} new'
                )
                if movie_links == 0:
                    empty_pages += 1
                    if empty_pages >= 2:
                        break
                else:
                    empty_pages = 0
                page += 1
                time.sleep(random.uniform(1, 2))

    def extract_articles(self, soup):
        """Find movie detail links on a listing page, ignoring category pages."""
        candidates = []
        seen_links = set()
        for link in soup.find_all('a', href=True):
            href = self.normalize_movie_link(link.get('href', ''))
            if not self.is_movie_link(href) or href in seen_links:
                continue
            title = self.clean_listing_title(link.get_text(' ', strip=True))
            candidates.append({'link': href, 'title': title})
            seen_links.add(href)
        return candidates
    
    def parse_article(self, article, soup=None, session=None):
        """Parse an article element and extract movie data"""
        try:
            # Handle different article formats
            title = ''
            link = ''
            thumbnail = ''
            description = ''
            
            # If article is a dict (from video_links), extract directly
            if isinstance(article, dict):
                link = article.get('link', '')
                title = article.get('title', '')
                
                # Find the actual article element in the page
                if link and soup:
                    article_elem = soup.find('a', href=link)
                    if article_elem:
                        # Try to find parent article or container
                        parent = article_elem.find_parent('article') or article_elem.find_parent(['div', 'li'])
                        if parent:
                            # Try to find thumbnail in parent
                            img = parent.find('img')
                            if img:
                                thumbnail = img.get('data-src') or img.get('data-lazy-src') or img.get('src', '')
                            
                            # Try to find description
                            excerpt = parent.find(['div', 'p'], class_=lambda x: x and 'excerpt' in x.lower())
                            if excerpt:
                                description = excerpt.get_text(strip=True)
            else:
                # Handle BeautifulSoup element
                # Get title and link
                title_link = article.find(['h2', 'h3'], class_=lambda x: x and 'title' in x.lower())
                if not title_link:
                    title_link = article.find('a')
                
                if title_link:
                    link_tag = title_link if title_link.name == 'a' else title_link.find('a')
                    if link_tag:
                        link = link_tag.get('href', '')
                        title = link_tag.get_text(strip=True)
                
                # Get thumbnail
                img = article.find('img')
                if img:
                    thumbnail = img.get('data-src') or img.get('data-lazy-src') or img.get('src', '')
                
                # Get description
                excerpt = article.find(['div', 'p'], class_=lambda x: x and 'excerpt' in x.lower())
                if excerpt:
                    description = excerpt.get_text(strip=True)
            
            link = self.normalize_movie_link(link)
            if not self.is_movie_link(link):
                return None
            title = self.clean_listing_title(title)

            detail_data = {}
            if session:
                detail_data = self.enrich_from_detail_page(
                    session,
                    link,
                    thumbnail=thumbnail,
                    description=description,
                )
                thumbnail = detail_data.get('thumbnail', thumbnail)
                description = detail_data.get('description', description)
                title = self.clean_listing_title(detail_data.get('title') or title)

            if not title:
                return None

            # Skip subtitle-only entries (e.g. ".srt" file downloads) — they
            # are not actual movies and should not appear in the catalogue.
            if self.is_subtitle_only(title, description):
                return None

            # Skip music videos and audio-only downloads (e.g. "Artist ft.
            # Other - Title (Mp3 Download)"). They are not movies and should
            # not appear in the catalogue.
            if self.is_music_or_audio(title, description):
                return None

            # Skip short-form comedy skits (e.g. Mark Angel Comedy,
            # YabaLeftOnline Comedy). These are weekly skit uploads, not
            # actual movies or TV series.
            if self.is_comedy_skit(title, description):
                return None

            info_year = (detail_data.get('video_info') or {}).get('Year', '')
            year = self.extract_year(title) or self.extract_year(f'({info_year})' if info_year else '')
            category = self.extract_category(title, description, detail_data.get('video_info'))
            # Defensive guard: never persist movies whose category is on the
            # excluded list (e.g. sport-live). This complements the
            # category-archive filter and protects against future scraper
            # changes that might reintroduce sport content.
            if category in EXCLUDED_CATEGORIES:
                return None
            movie_id = self.generate_id(title)
            movie = {
                'id': movie_id,
                'title': title,
                'description': description,
                'thumbnail': thumbnail,
                'link': link,
                'year': year,
                'category': category,
                'source': '9jarocks',
                'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            movie.update({key: value for key, value in detail_data.items() if key != 'title'})
            return movie
            
        except Exception as e:
            # Silently skip problematic articles
            return None

    def enrich_from_detail_page(self, session, link, thumbnail='', description=''):
        """Fetch the detail page to fill missing poster and rich detail data.

        Bug fixed: the previous implementation swallowed every
        `requests.RequestException` silently, which meant that any time the
        detail-page request failed (timeout, 403, Cloudflare challenge, …)
        the movie was still saved to the catalog with EMPTY `video_info`,
        `download_links`, `screenshots`, and `trailer_url`. That produced
        records that looked like the scraper hadn't finished scraping the
        movie.

        We now route the request through `fetch_page` (which retries and
        falls back between bare and `www.` hosts), detect Cloudflare's
        managed challenge page, log the failure to stdout, and expose
        `detail_page_ok` / `detail_page_error` on the returned dict so the
        caller can decide whether to keep or discard the partial record.
        """
        detail_data = {
            'title': '',
            'thumbnail': thumbnail,
            'description': description,
            'video_info': {},
            'trailer_url': '',
            'trailer_embed_url': '',
            'trailer_title': '',
            'download_links': [],
            'download_help_url': '',
            'screenshots': [],
            'detail_page_ok': False,
            'detail_page_error': '',
        }
        try:
            parsed = urlparse(link)
            path = parsed.path or '/'
            response = self.fetch_page(session, path)
        except requests.RequestException as error:
            detail_data['detail_page_error'] = f'{type(error).__name__}: {error}'
            self.stdout.write(self.style.WARNING(
                f'Detail page failed for {link}: {detail_data["detail_page_error"]}'
            ))
            return detail_data

        soup = BeautifulSoup(response.content, 'html.parser')
        if self.is_cloudflare_challenge(soup, response.text):
            detail_data['detail_page_error'] = 'cloudflare-challenge'
            self.stdout.write(self.style.WARNING(
                f'Detail page returned a Cloudflare challenge for {link}; '
                'movie will have incomplete data.'
            ))
            return detail_data

        detail_data['detail_page_ok'] = True
        detail_data['title'] = self.extract_detail_title(soup)

        detail_thumbnail = self.extract_detail_thumbnail(soup)
        if detail_thumbnail:
            detail_data['thumbnail'] = detail_thumbnail

        if not detail_data['description']:
            detail_data['description'] = self.extract_detail_description(soup)

        detail_data['video_info'] = self.extract_video_information(soup)
        detail_data.update(self.extract_trailer_data(soup))
        detail_data['download_links'] = self.extract_download_links(soup)
        detail_data['download_help_url'] = self.extract_download_help_url(soup)
        detail_data['screenshots'] = self.extract_screenshots(soup)
        return detail_data

    def is_cloudflare_challenge(self, soup, raw_html=''):
        """Detect Cloudflare's managed/JS challenge pages.

        These return HTTP 200 with a tiny body containing `cf-mitigated` and
        a script from `challenges.cloudflare.com`. Treating them as success
        silently produced empty movie records.
        """
        if not raw_html:
            return False
        lowered = raw_html.lower()
        if 'cf-mitigated' in lowered or 'challenges.cloudflare.com' in lowered:
            return True
        title_tag = soup.find('title')
        title_text = title_tag.get_text(' ', strip=True).lower() if title_tag else ''
        return 'just a moment' in title_text or 'attention required' in title_text

    def extract_detail_title(self, soup):
        """Prefer the detail-page heading over listing cards that include ratings."""
        heading = soup.find(['h1', 'h2'], class_=lambda value: value and 'post-title' in str(value))
        if heading:
            text = self.clean_listing_title(heading.get_text(' ', strip=True))
            if text:
                return text
        meta = soup.find('meta', attrs={'property': 'og:title'})
        if meta and meta.get('content'):
            return self.clean_listing_title(meta['content'].split('|')[0])
        if soup.title and soup.title.string:
            return self.clean_listing_title(soup.title.string.split('|')[0])
        return ''

    def clean_listing_title(self, title):
        if not title:
            return ''
        title = re.sub(r'\s+\d+(?:\.\d+)?\s*\(\d+\)\s*$', '', title).strip()
        return re.sub(r'\s+', ' ', title).strip()

    def extract_detail_thumbnail(self, soup):
        """Extract the most useful poster-like image from a detail page."""
        meta = soup.find('meta', attrs={'property': 'og:image'})
        if meta and self.is_valid_thumbnail(meta.get('content', '')):
            return self.normalize_url(meta['content'].strip())

        twitter = soup.find('meta', attrs={'name': 'twitter:image'})
        if twitter and self.is_valid_thumbnail(twitter.get('content', '')):
            return self.normalize_url(twitter['content'].strip())

        for img in soup.find_all('img'):
            candidate = (
                img.get('src')
                or img.get('data-src')
                or img.get('data-lazy-src')
                or ''
            ).strip()
            if self.is_valid_thumbnail(candidate):
                return self.normalize_url(candidate)

        return ''

    def extract_detail_description(self, soup):
        """Extract a synopsis-like paragraph from the detail page."""
        article = soup.find('article')
        if article:
            for paragraph in article.find_all('p'):
                text = paragraph.get_text(' ', strip=True)
                if self.is_valid_description(text):
                    return text

        for paragraph in soup.find_all('p'):
            text = paragraph.get_text(' ', strip=True)
            if self.is_valid_description(text):
                return text

        return ''

    def extract_video_information(self, soup):
        """Parse the VIDEO INFORMATION block into labeled fields.

        The block on 9jarocks is rendered in different layouts:
          * Most pages: a single <p> (with <br> separators) immediately after
            the <strong>VIDEO INFORMATION</strong> heading.
          * Some pages (e.g. Wura Season 4): the <p>Filename: ...</p> lives
            INSIDE a <blockquote> sibling, with a "Related Articles" sidebar
            <div> wedged between the heading and the blockquote.

        We walk up to 16 next siblings of type <p>/<div>/<blockquote>,
        SKIP over "Related Articles" widgets, and STOP at the next major
        section (TRAILER / DOWNLOAD LINKS / SCREENSHOT). All collected
        text is concatenated before the labels are parsed, so multi-paragraph
        info blocks are also handled.
        """
        info_heading = soup.find(
            lambda tag: tag.name in ['strong', 'h2', 'h3', 'h4', 'b']
            and 'video information' in tag.get_text(' ', strip=True).lower()
        )
        if not info_heading:
            return {}

        # Keywords that mark the END of the video info section.
        stop_keywords = (
            'trailer', 'download links', 'screenshot',
            'related articles', 'read next', 'more on',
            'submit rating', 'requests & upload',
        )
        chunks = []
        for sibling in info_heading.find_all_next(
            ['p', 'div', 'blockquote'], limit=16
        ):
            text = sibling.get_text(' ', strip=True)
            if not text:
                continue
            lowered = text.lower()
            # Skip the "Related Articles" sidebar widget — the real info
            # block often sits after it on pages like Wura Season 4.
            if 'related articles' in lowered and 'filename' not in lowered:
                continue
            # Stop at the next major section heading (only when it's a
            # short label, not a paragraph that merely mentions the word).
            if len(lowered) < 40 and any(
                lowered.startswith(k) for k in stop_keywords
            ):
                break
            chunks.append(text)
            # Subtitle is conventionally the last label in the block.
            if 'subtitle:' in lowered:
                break

        info_text = re.sub(r'\s+', ' ', ' '.join(chunks)).strip()
        if not info_text or 'filename' not in info_text.lower():
            return {}

        # "Related Articles" is a sidebar widget whose text is sometimes
        # concatenated onto the end of the video info <p> by the page
        # template. Nothing useful for us lives after it, so truncate.
        related_idx = info_text.lower().find('related articles')
        if related_idx != -1:
            info_text = info_text[:related_idx].strip()

        extracted = {}
        positions = []
        for label in self.VIDEO_INFO_LABELS:
            match = re.search(rf'{re.escape(label)}\s*:', info_text, flags=re.IGNORECASE)
            if match:
                positions.append((match.start(), match.end(), label))

        positions.sort(key=lambda item: item[0])
        for index, (_, value_start, label) in enumerate(positions):
            next_start = positions[index + 1][0] if index + 1 < len(positions) else len(info_text)
            value = info_text[value_start:next_start].strip(' :-')
            if value:
                extracted[label] = value

        return extracted

    def extract_trailer_data(self, soup):
        """Extract trailer URLs from embeds or YouTube links."""
        trailer_data = {
            'trailer_url': '',
            'trailer_embed_url': '',
            'trailer_title': '',
        }

        iframe = soup.find('iframe', src=lambda value: value and 'youtube.com' in value)
        if iframe:
            trailer_data['trailer_embed_url'] = iframe.get('src', '').strip()
            trailer_data['trailer_title'] = iframe.get('title', '').strip()

        if trailer_data['trailer_embed_url']:
            trailer_data['trailer_url'] = self.youtube_watch_url_from_embed(trailer_data['trailer_embed_url'])

        if not trailer_data['trailer_url']:
            trailer_link = soup.find('a', href=lambda value: value and ('youtube.com/watch' in value or 'youtu.be/' in value))
            if trailer_link:
                trailer_data['trailer_url'] = trailer_link.get('href', '').strip()
                trailer_data['trailer_title'] = trailer_link.get_text(' ', strip=True)

        return trailer_data

    def extract_download_links(self, soup):
        """Collect download links and their labels from the download section."""
        download_links = []
        download_hosts = (
            'loadedfiles.net',
            'pixeldrain.com',
            'gofile.io',
            'mediafire.com',
            'mega.nz',
            'drive.google.com',
        )
        for anchor in soup.find_all('a', href=lambda value: value and any(host in value for host in download_hosts)):
            parent = anchor.find_parent('p')
            label = 'Download'
            if parent:
                parent_text = parent.get_text(' ', strip=True)
                label = re.sub(r'\bDOWNLOAD\b', '', parent_text, flags=re.IGNORECASE).strip(' :-') or 'Download'

            download_links.append({
                'label': label,
                'url': anchor.get('href', '').strip(),
                'text': anchor.get_text(' ', strip=True) or 'DOWNLOAD',
            })

        return download_links

    def extract_download_help_url(self, soup):
        """Find the helper page used in the download links section."""
        help_link = soup.find(
            'a',
            href=lambda value: value and 'how-to-download' in value.lower()
        )
        return help_link.get('href', '').strip() if help_link else ''

    def extract_screenshots(self, soup):
        """Extract images contained in the article's SCREENSHOT block.

        Bug fixed: the previous implementation only scanned the *parent* of
        the SCREENSHOT heading, which misses any screenshots that live in
        sibling elements (e.g. when the heading sits in its own <p> and the
        screenshot <img> sits in a sibling <p> or <blockquote>). We now
        walk up to 8 sibling elements after the heading's parent, collecting
        every image until we hit the next major section
        (Related Articles / Read Next / MORE ON / Submit Rating).
        """
        heading = soup.find(
            lambda tag: tag.name in ['strong', 'h2', 'h3', 'h4', 'b']
            and 'screenshot' in tag.get_text(' ', strip=True).lower()
        )
        if not heading:
            return []

        container = heading.find_parent(['p', 'div', 'section', 'blockquote'])
        screenshots = []
        seen = set()

        stop_keywords = (
            'related articles', 'read next', 'more on',
            'submit rating', 'requests & upload',
        )

        def collect_from(node):
            if not node or not hasattr(node, 'find_all'):
                return
            for image in node.find_all('img'):
                candidate = (
                    image.get('src')
                    or image.get('data-src')
                    or image.get('data-lazy-src')
                    or ''
                ).strip()
                if not self.is_valid_thumbnail(candidate):
                    continue
                normalized = self.normalize_url(candidate)
                if normalized in seen:
                    continue
                seen.add(normalized)
                screenshots.append(normalized)

        # 1. The heading's own container (often wraps the first screenshot).
        collect_from(container)

        # 2. Walk forward through sibling paragraphs/blockquotes/divs until
        #    the next major section heading. This is where additional
        #    screenshots live when a title has a multi-image gallery.
        if container is not None:
            sibling = container.find_next_sibling()
            walked = 0
            while sibling is not None and walked < 8:
                if hasattr(sibling, 'get_text'):
                    sibling_text = sibling.get_text(' ', strip=True).lower()
                    if any(k in sibling_text for k in stop_keywords):
                        break
                collect_from(sibling)
                sibling = sibling.find_next_sibling()
                walked += 1

        return screenshots

    def youtube_watch_url_from_embed(self, embed_url):
        if not embed_url:
            return ''

        parsed = urlparse(embed_url)
        if 'youtube.com' not in parsed.netloc:
            return embed_url

        if '/embed/' in parsed.path:
            video_id = parsed.path.rsplit('/embed/', 1)[-1]
            video_id = video_id.split('?', 1)[0]
            return f'https://www.youtube.com/watch?v={video_id}'

        query = parse_qs(parsed.query)
        if 'v' in query and query['v']:
            return f'https://www.youtube.com/watch?v={query["v"][0]}'
        return embed_url

    def is_valid_thumbnail(self, url):
        """Filter out placeholders and button graphics."""
        if not url or url.startswith('data:image'):
            return False

        lowered = url.lower()
        blocked_fragments = [
            'download-button',
            'telegram',
            'guest',
            'avatar',
            'emoji',
            'logo',
            'placeholder',
            'default-image',
            'no-image',
            'no_image',
            'fallback',
        ]
        return not any(fragment in lowered for fragment in blocked_fragments)

    def is_placeholder_thumbnail(self, url):
        """Identify saved generic site artwork so a detail poster can replace it."""
        lowered = (url or '').lower()
        return any(fragment in lowered for fragment in (
            'logo', 'placeholder', 'default-image', 'no-image', 'no_image', 'fallback',
        ))

    def is_valid_description(self, text):
        """Filter out labels and boilerplate when searching for a synopsis."""
        if not text:
            return False

        lowered = text.lower()
        blocked_prefixes = (
            'video information',
            'filename:',
            'filesize:',
            'duration:',
            'imdb:',
            'title:',
            'year:',
            'type:',
            'country:',
            'language:',
            'director:',
            'genre:',
            'stars:',
            'subtitle:',
            'download links',
            'screenshot',
            'related articles',
            'trailer',
            'more on',
            'tags',
        )
        if lowered.startswith(blocked_prefixes):
            return False
        return len(text) > 40

    def normalize_url(self, url):
        if url.startswith('//'):
            return f'https:{url}'
        if url.startswith('/'):
            return f'https://9jarocks.net{url}'
        return url
    
    def extract_year(self, title):
        """Extract year from title using regex"""
        patterns = [
            r'\((\d{4})\)',
            r'\b((?:19|20)\d{2})\b',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, title)
            if match:
                year = match.group(1) if match.groups() else match.group(0)
                if len(year) == 4:
                    return int(year)
        
        return None
    
    def extract_category(self, title, description, video_info=None):
        """Try to determine movie category"""
        title_lower = title.lower()
        desc_lower = description.lower() if description else ''
        text = f'{title_lower} {desc_lower}'

        # Sport content (football match highlights, WWE, UFC, etc.) is not
        # part of the site's catalogue. Detect it before any other rule so
        # it is reported as an excluded category and dropped by parse_article.
        if self.is_sport_title(text):
            return 'sport-live'

        return classify_movie_category(title, description, metadata=video_info)

    # Patterns that flag a title as sport content (match highlights, wrestling,
    # league fixtures, etc.). They are deliberately specific to avoid false
    # positives on real movies and TV series.
    SPORT_TITLE_PATTERNS = [
        r'all\s+goals',
        r'all\s+highlights?',
        r'goals?\s*(&|and)\s*highlights?',
        r'highlights?\s*(&|and)\s*goals?',
        r'match\s+highlights?',
        r'extended\s+highlights?',
        r'highlights?\s*[-:]\s*\d{4}',
        r'highlights?\s*[-:]\s*\d{1,2}[-/]\d{1,2}[-/]\d{2,4}',
        # League tags with surrounding sport context (covers both orders).
        r'\bepl\b.*(?:video|goals?|highlights?)',
        r'(?:video|goals?|highlights?).*\bepl\b',
        r'epl\s+video\s*:',
        r'\bucl\b.*(?:video|goals?|highlights?)',
        r'(?:video|goals?|highlights?).*\bucl\b',
        r'ucl\s+video\s*:',
        r'\bwcq\b.*(?:video|goals?|highlights?)',
        r'(?:video|goals?|highlights?).*\bwcq\b',
        r'wcq\s+video\s*:',
        r'fa\s+cup\s+video',
        r'la\s+liga\s+video',
        r'europa\s+league\s+video',
        r'premier\s+league',
        r'champions\s+league',
        r'europa\s+league',
        r'super\s+cup',
        r'world\s+cup\s+qualifiers?',
        r'afcon\s+qualifiers',
        r'icc:\s',
        r'\buefa\b',
        r'\bwwe\b',
        r'aew\s+collision',
        r'smackdown',
        r'\bufc\b',
        r'\bnfl\b',
        r'\bnba\b',
        r'\bnhl\b',
        r'\bmlb\b',
        r'\bboxing\b',
        r'wrestling',
        r'vs\.?\s+\w+.*(?:goals?|highlights?)',
        r'#premierleague',
        r'goals?\s*[-–]\s*\d',
        # Wrestling promotions / shows / PPVs (catch all wrestling content).
        r'\bwrestlemania\b',
        r'\broyal\s+rumble\b',
        r'\bsummerslam\b',
        r'\bsurvivor\s+series\b',
        r'\bsummerslam\b',
        r'\bnjpw\b',
        r'\bimpact\s+wrestling\b',
        r'\bring\s+of\s+honor\b',
        r'\bdynamite\b.*\bwrestling',
        r'\brampage\b.*\bwrestling',
        r'raw\s+vs\s+smackdown',
        r'\bnxt\b.*\bwrestling',
        r'aew\s+dynamite',
        r'aew\s+rampage',
        r'aew\s+revolution',
        r'aew\s+double\s+or\s+nothing',
        r'wwe\s+raw',
        r'wwe\s+smackdown',
        r'wwe\s+nxt',
        r'wwe\s+payback',
        r'wwe\s+elimination\s+chamber',
        r'wwe\s+money\s+in\s+the\s+bank',
        r'wwe\s+extreme\s+rules',
        r'wwe\s+hell\s+in\s+a\s+cell',
        r'wwe\s+tlc',
        r'wwe\s+fastlane',
        r'wwe\s+clash',
        r'wwe\s+backlash',
        r'wwe\s+night\s+of\s+champions',
        r'wwe\s+battleground',
        r'wwe\s+great\s+ball\s+of\s+fire',
        r'wwe\s+stomping\s+grounds',
        r'aew\s+all\s+out',
        r'aew\s+full\s+gear',
        r'aew\s+fight\s+for\s+the\s+fallen',
        # Combat sports generic — phrase-level to avoid false positives on
        # movie/TV character names (e.g. the cartoon character "Sumo").
        r'\bmma\b',
        r'\bjudo\b',
        r'\btaekwondo\b',
        r'\bkarate\b.*(?:championship|tournament|fight)',
        r'sumo\s+wrestling',
        r'sumo\s+tournament',
        # Boxing / combat-sport outcome patterns. These phrase patterns are
        # very specific to fight results and won't appear in real movie titles.
        r'wins?\s+by\s+(?:TKO|KO|decision|submission|technical\s+decision)',
        r'loses?\s+by\s+(?:TKO|KO|decision|submission|technical\s+decision)',
        r'\bTKO\s+in\s+the\s+\d',
        r'\bKO\s+in\s+(?:round|the\s+\d)',
        r'\bknockout\s+in\s+round\b',
        r'\bround\s+\d+\s*:\s*(?:TKO|KO|decision|submission)',
        r'\bboxing\s+(?:match|championship|fight|bout)\b',
        r'\bfight\s+night\b',
        r'\bchampionship\s+bout\b',
        r'\btitle\s+bout\b',
        r'\bheavyweight\s+(?:champion|championship|title|fight|bout)\b',
        r'\bwelterweight\s+(?:champion|championship|title|fight|bout)\b',
        r'\bmiddleweight\s+(?:champion|championship|title|fight|bout)\b',
        # Combat-sport promotion names.
        r'\bbellator\b',
        r'\bone\s+championship\b',
        r'\bk-1\b.*(?:grand\s+prix|championship)',
        r'\bglory\s+kickboxing\b',
        r'\bmuay\s+thai\b',
        # 'vs ... wins/loses' pattern: catches "Mayweather vs McGregor –
        # Mayweather wins by TKO" without false-positiving on movies like
        # "Batman v Superman" (which has no fight outcome wording).
        r'vs\.?\s+\w+.*\b(?:wins?|loses?|defeats?)\b.*\b(?:TKO|KO|round|decision|submission|knockout)',
        r'\b(?:wins?|loses?|defeats?)\b.*vs\.?.*\b(?:TKO|KO|round|decision|submission|knockout)',
        # Famous boxer/MMA fighter surnames. These are specific enough that
        # false positives on real movie/TV titles are extremely unlikely.
        r'\bmayweather\b',
        r'\bpacquiao\b',
        r'\bkhabib\b',
        r'\bjon\s+jones\s+vs\b',
        r'\bdaniel\s+cormier\b',
        r'\bstipe\s+miocic\b',
        r'\bmike\s+tyson\b',
        r'\btyson\s+fury\b',
        r'\banthony\s+joshua\b',
        r'\bdeontay\s+wilder\b',
        r'\bevander\s+holyfield\b',
        r'\bkubrat\s+pulev\b',
        r'\bcanelo\s+alvarez\b',
        r'\bconor\s+mcgregor\b',
        r'\b Israel\s+adesanya\b',
        # 'vs ... full fight' / 'vs ... fight' / 'vs ... champion' — common
        # combat-sport title patterns not seen in real movies.
        r'vs\.?\s+\w+.*\b(?:full\s+fight|fight\s+video|champion|title\s+fight)\b',
        # Motor sport events.
        r'\bgrand\s+prix\b',
        r'\bformula\s+1\b',
        r'\bmotogp\b',
        r'\bnascar\b',
        r'\bindy\s*500\b',
        r'\ble\s*mans\b',
    ]
    SPORT_TITLE_REGEX = re.compile('|'.join(SPORT_TITLE_PATTERNS), re.IGNORECASE)

    def is_sport_title(self, text):
        """Return True when the text looks like sport-highlight content."""
        return bool(self.SPORT_TITLE_REGEX.search(text or ''))

    # Patterns that flag an entry as a subtitle-only download rather than a
    # real movie (e.g. ".srt" subtitle files shared on the source site).
    SUBTITLE_ONLY_PATTERNS = [
        r'subtitle\s+srt',
        r'\.srt\b',
        r'\bsrt\b.*subtitle',
        r'subtitle\s*file',
        r'subtitle\s*pack',
    ]
    SUBTITLE_ONLY_REGEX = re.compile('|'.join(SUBTITLE_ONLY_PATTERNS), re.IGNORECASE)

    def is_subtitle_only(self, title, description):
        """Return True when the entry looks like a subtitle-only download."""
        return bool(self.SUBTITLE_ONLY_REGEX.search(f"{title or ''} {description or ''}"))

    # Patterns that flag an entry as a music video / audio-only download
    # rather than a real movie (e.g. "Artist ft. Other - Title (Mp3 Download)"
    # or "VIDEO: Artist ft. Other - Title").
    MUSIC_AUDIO_PATTERNS = [
        # Title starts with VIDEO: / Download Video: / Search Playlist VIDEO:
        # (typical music-video post format on the source site)
        r'^\s*(?:VIDEO|Download\s+Video|Search\s+Playlist\s+VIDEO)\s*:',
        # Mp3 / freestyle / audio download markers
        r'\bMp3\s+Download\b',
        r'\bMP3\s+Download\b',
        r'\bDOWNLOAD\s+MP3\b',
        r'\bfreestyle\b',
        r'\baudio\s+download\b',
        # ft./feat. + artist-name pattern (typical music-title structure)
        r'\bft\.?\s+[A-Z]',
        r'\bfeat\.?\s+[A-Z]',
        # Song-title pattern: "Artist – \"Title\"" (en-dash + curly quote).
        # This is almost never seen in real movie titles but is extremely
        # common in music-video posts. We pair it with music-specific
        # description context to avoid false-positives on comedy-skits that
        # also use curly quotes or "Mp4 Download".
        r'–\s*[\u201c\u2018\u2019\u201d].*(?:dishes|groovy|visuals|single\s+entitled|spanking\s+new|track\s+titled|cut\s+titled)',
        r'(?:dishes|groovy|visuals|single\s+entitled|spanking\s+new|track\s+titled|cut\s+titled).*–\s*[\u201c\u2018\u2019\u201d]',
        # Music-video description phrases used by the source site
        r'dishes\s+out\s+the\s+video',
        r'groovy\s+cut',
        r'drops?\s+(?:her|his|their)\s+(?:first|second|third|new|latest)\s+(?:video|single|song)\b',
        r'releases?\s+(?:the\s+)?(?:visuals?|video)\s+to\b',
        r'unleashes?\s+the\s+visuals?\b',
        r'shares\s+the\s+visuals?\b',
        r'\bsingle\s+entitled\b',
        r'\bspanking\s+new\s+single\b',
        r'\btrack\s+titled\b',
        r'\bcut\s+titled\b',
        # More music-label / video-phrase markers
        r'\bpresents\s+clean\s+and\s+crisp\s+visuals?\b',
        r'\bU\s*&\s*I\s+Music\b',
        r'\bcrooner\b',
        r'\bAkube\b',
        r'-video\s+to\b',
        r'\bname\s+on\s+everyone\'?s\s+lips\b',
        # Common Nigerian/African music artists
        r'\bFuse\s+ODG\b', r'\bMr\s+Eazi\b', r'\bTiwa\s+Savage\b',
        r'\bMayorkun\b', r'\bIce\s+Prince\b',
        r'\bPatoranking\b', r'\bMz\s+Kiss\b', r'\bFalz\b',
        r'\bSean\s+Tizzle\b', r'\bDax\s+Mpire\b',
        r'\bsmall\s+DOCTOR\b', r'\bZinnia\b',
        # AUDIO & VIDEO marker
        r'^\s*AUDIO\s+&\s+VIDEO\b',
        r'\bOfficial\s+Video\b',
        # 'freestyle', 'cover freestyle'
        r'\bCover\s+Freestyle\b',
        r'\bSwalla\s+Cover\b',
    ]
    MUSIC_AUDIO_REGEX = re.compile('|'.join(MUSIC_AUDIO_PATTERNS), re.IGNORECASE)

    def is_music_or_audio(self, title, description):
        """Return True when the entry looks like a music video or audio download."""
        return bool(self.MUSIC_AUDIO_REGEX.search(f"{title or ''} {description or ''}"))

    # Patterns that flag an entry as a short-form comedy skit rather than a
    # real movie or TV series. These are weekly skit uploads (e.g. Mark Angel
    # Comedy, YabaLeftOnline Comedy) and are not part of the movie catalogue.
    # Note: real comedy films like "Kevin Hart: What Now?" are NOT matched
    # because they don't use skit-series markers.
    COMEDY_SKIT_PATTERNS = [
        # Explicit skit-post prefixes used by the source site
        r'^\s*(?:COMEDY\s+SKIT|COMEDY\s+VIDEO|DOWNLOAD\s+COMEDY\s+SKIT)\b',
        # Series-name markers — these are well-known Nigerian skit series
        r'\bMark\s+Angel\s+Comedy\b',
        r'\bYabaLeftOnline\s+Comedy\b',
        r'\bYaba\s+Left\s+Online\s+Comedy\b',
        # Description markers used by skit posts
        r'\bYabaLeftOnline\.com\s+Team\b',
        r'\bweekly\s+Comedy\s+Series\b',
    ]
    COMEDY_SKIT_REGEX = re.compile('|'.join(COMEDY_SKIT_PATTERNS), re.IGNORECASE)

    def is_comedy_skit(self, title, description):
        """Return True when the entry looks like a short-form comedy skit."""
        return bool(self.COMEDY_SKIT_REGEX.search(f"{title or ''} {description or ''}"))

    
    def generate_id(self, title):
        """Generate a URL-friendly ID from title"""
        # Remove special characters and convert to lowercase
        clean = re.sub(r'[^\w\s-]', '', title.lower())
        # Replace spaces with hyphens
        clean = re.sub(r'\s+', '-', clean.strip())
        # Remove multiple hyphens
        clean = re.sub(r'-+', '-', clean)
        return clean[:50]  # Limit length
