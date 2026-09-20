from django.db import migrations


def reclassify_nigerian_titles(apps, schema_editor):
    Movie = apps.get_model('core', 'Movie')
    for movie in Movie.objects.all().iterator():
        text = f'{movie.title} {movie.description}'.lower()
        if any(marker in text for marker in ('nollywood', 'nigerian', 'naija', 'ghana')):
            category = 'nollywood-tv-series' if any(
                marker in text for marker in ('season', 'episode', 'series', 'tv series')
            ) else 'nollywood-movie'
            if movie.category != category:
                Movie.objects.filter(pk=movie.pk).update(category=category)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0014_normalize_category_slugs'),
    ]

    operations = [
        migrations.RunPython(reclassify_nigerian_titles, migrations.RunPython.noop),
    ]