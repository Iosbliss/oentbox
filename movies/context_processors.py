"""Context processor for global template variables."""
from .models import Category


def categories_context(request):
    return {
        "global_categories": Category.objects.filter(is_active=True).order_by("order", "name"),
        "SITE_NAME": "OentBox",
        "SITE_TAGLINE": "Stream & Download Nollywood, Hollywood, K-Drama & More",
    }
