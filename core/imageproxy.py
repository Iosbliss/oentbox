"""Local cache and optimiser for remote poster images.

Every card on the site points at a poster hotlinked from the scraped source, so
pages depend on a third party's uptime and ship unoptimised JPEGs. This module
fetches each poster once, resizes it and re-encodes it as WebP into a directory
that nginx serves directly with a long-lived immutable cache.

Two URL shapes are produced:
  * ``/imgcache/<hash>-<width>w.webp`` once the optimised file exists (nginx
    serves it, Django is not involved at all), and
  * ``/img?u=<remote>&w=<width>`` while it is still missing, which optimises the
    image and redirects the client to the cached file.

Only hosts in ALLOWED_HOSTS may be fetched, so the proxy cannot be used to
reach arbitrary URLs.
"""
import hashlib
import os
import urllib.parse
import urllib.request
from io import BytesIO

from django.http import HttpResponseRedirect

CACHE_DIR = os.environ.get("IMAGE_CACHE_DIR", "/opt/oentbox/image-cache")
CACHE_URL_PREFIX = "/imgcache/"
PLACEHOLDER = "/static/img/icon-o.svg"

ALLOWED_HOSTS = {
    "9jarocks.net",
    "www.9jarocks.net",
    "my9jarocks.bz",
    "www.my9jarocks.bz",
    "image.tmdb.org",
    "images.justwatch.com",
    "resizing.flixster.com",
}
ALLOWED_WIDTHS = (160, 300, 480, 780)
DEFAULT_WIDTH = 300
WEBP_QUALITY = int(os.environ.get("IMAGE_WEBP_QUALITY", "78"))
MAX_BYTES = 8 * 1024 * 1024
FETCH_TIMEOUT = 10
USER_AGENT = "Mozilla/5.0 (compatible; oentbox-image-cache/1.0; +https://oentbox.com)"


def is_allowed_url(url):
    """True only for http(s) URLs on a poster host we are allowed to fetch."""
    try:
        parts = urllib.parse.urlsplit(url or "")
    except ValueError:
        return False
    if parts.scheme not in ("http", "https"):
        return False
    return (parts.hostname or "").lower() in ALLOWED_HOSTS


def normalize_width(width):
    """Snap a requested width to the nearest supported size."""
    try:
        width = int(width)
    except (TypeError, ValueError):
        return DEFAULT_WIDTH
    if width <= 0:
        return DEFAULT_WIDTH
    for allowed in ALLOWED_WIDTHS:
        if width <= allowed:
            return allowed
    return ALLOWED_WIDTHS[-1]


def cache_name(url, width):
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]
    return "%s-%dw.webp" % (digest, normalize_width(width))


def cache_path(name):
    return os.path.join(CACHE_DIR, name)


def cached_url(url, width):
    """Direct nginx path when the optimised file already exists, else ""."""
    if not url:
        return ""
    name = cache_name(url, width)
    try:
        if os.path.exists(cache_path(name)) and os.path.getsize(cache_path(name)) > 0:
            return CACHE_URL_PREFIX + name
    except OSError:
        return ""
    return ""


def proxy_url(url, width):
    """Optimiser route for a remote image, or "" when the host is not allowed."""
    if not is_allowed_url(url):
        return ""
    return "/img?u=%s&w=%d" % (urllib.parse.quote(url, safe=""), normalize_width(width))


def poster_url(url, width=DEFAULT_WIDTH):
    """Best available poster URL: nginx cache, else optimiser route, else original."""
    if not url:
        return ""
    direct = cached_url(url, width)
    if direct:
        return direct
    return proxy_url(url, width) or url


def ensure_cached(url, width=DEFAULT_WIDTH):
    """Fetch, resize and store one poster. Returns the cache file name or ""."""
    if not is_allowed_url(url):
        return ""
    width = normalize_width(width)
    name = cache_name(url, width)
    path = cache_path(name)
    try:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return name
    except OSError:
        return ""

    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "image/*,*/*;q=0.8"}
        )
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            if content_type and not content_type.startswith("image/"):
                return ""
            data = response.read(MAX_BYTES + 1)
    except Exception:
        return ""
    if not data or len(data) > MAX_BYTES:
        return ""

    try:
        from PIL import Image

        with Image.open(BytesIO(data)) as image:
            image = image.convert("RGB")
            image.thumbnail((width, width * 6), Image.LANCZOS)
            buffer = BytesIO()
            image.save(buffer, format="WEBP", quality=WEBP_QUALITY, method=5)
            payload = buffer.getvalue()
    except Exception:
        return ""
    if not payload:
        return ""

    temp = "%s.%d.part" % (path, os.getpid())
    try:
        with open(temp, "wb") as handle:
            handle.write(payload)
        os.replace(temp, path)
    except OSError:
        try:
            os.unlink(temp)
        except OSError:
            pass
        return ""
    return name


def image_proxy(request):
    """Optimise one remote poster, then redirect the client to the cached file."""
    remote = request.GET.get("u", "")
    if not is_allowed_url(remote):
        # never serve arbitrary URLs, and never leave a broken image behind
        return HttpResponseRedirect(remote if remote.startswith("http") else PLACEHOLDER)
    name = ensure_cached(remote, request.GET.get("w", DEFAULT_WIDTH))
    if not name:
        return HttpResponseRedirect(remote)
    return HttpResponseRedirect(CACHE_URL_PREFIX + name)
