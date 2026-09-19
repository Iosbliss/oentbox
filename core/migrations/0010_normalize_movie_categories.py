from django.db import migrations


def normalize_categories(apps, schema_editor):
    Movie = apps.get_model('core', 'Movie')
    specific_keywords = (
        ('anime', ('anime', 'cartoon', 'animation')),
        ('korean-drama', ('korean', 'k-drama', 'kdrama')),
        ('chinese-drama', ('chinese', 'c-drama', 'cdrama')),
        ('japanese-drama', ('japanese', 'j-drama', 'jdrama')),
        ('filipino-drama', ('filipino', 'philippines')),
        ('turkish-drama', ('turkish', 'turkey')),
        ('thai-drama', ('thai', 'thailand')),
    )
    for movie in Movie.objects.exclude(category__in={'sport-live', 'sport', 'sports', 'wrestling', 'wrestling-live'}).iterator():
        text = f'{movie.title} {movie.description or ""}'.lower()
        category = next((name for name, keywords in specific_keywords if any(keyword in text for keyword in keywords)), None)
        series = any(keyword in text for keyword in ('season', 'episode', 'series', 'tv series'))
        if not category:
            if any(keyword in text for keyword in ('nollywood', 'nigerian', 'ghana')) or movie.category == 'nollywood':
                category = 'nollywood-tv-series' if series else 'nollywood-movie'
            elif any(keyword in text for keyword in ('hollywood', 'american', 'usa', 'u.s.a')) or movie.category in {'hollywood', 'tv-series'}:
                category = 'hollywood-tv-series' if series or movie.category == 'tv-series' else 'hollywood-movie'
            else:
                category = 'other-foreign-series' if series else 'foreign-movie'
        Movie.objects.filter(pk=movie.pk).update(category=category)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0009_scraperun_progress'),
    ]

    operations = [migrations.RunPython(normalize_categories, migrations.RunPython.noop)]