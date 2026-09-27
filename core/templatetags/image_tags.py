"""Template helpers for the local poster cache."""
from django import template

from core import imageproxy

register = template.Library()


@register.filter(name="poster")
def poster(url, width=imageproxy.DEFAULT_WIDTH):
    """Return a locally cached poster URL, falling back to the optimiser route."""
    return imageproxy.poster_url(url, width)


@register.simple_tag
def poster_direct(url, width=imageproxy.DEFAULT_WIDTH):
    """Direct nginx URL for an already optimised poster, else the original."""
    return imageproxy.cached_url(url, width) or (url or "")
