from django.db import migrations


def separate_bollywood_categories(apps, schema_editor):
    from core.movie_data import classify_movie_category

    Movie = apps.get_model('core', 'Movie')
    for movie in Movie.objects.all().iterator():
        text = f'{movie.title} {movie.description}'.lower()
        if 'bollywood' not in text:
            continue
        series = any(marker in text for marker in ('season', 'episode', 'series', 'tv series'))
        category = 'bollywood-tv-series' if series else 'bollywood-movie'
        if movie.category != category:
            Movie.objects.filter(pk=movie.pk).update(category=category)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0017_reclassify_bollywood_titles'),
    ]

    operations = [
        migrations.RunPython(separate_bollywood_categories, migrations.RunPython.noop),
    ]