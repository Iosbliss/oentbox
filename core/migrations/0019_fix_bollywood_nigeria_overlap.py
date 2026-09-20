from django.db import migrations


def fix_bollywood_nigeria_overlap(apps, schema_editor):
    Movie = apps.get_model('core', 'Movie')
    queryset = Movie.objects.filter(title__icontains='bollywood')
    for movie in queryset.iterator():
        text = f'{movie.title} {movie.description}'.lower()
        series = any(marker in text for marker in ('season', 'episode', 'series', 'tv series'))
        category = 'bollywood-tv-series' if series else 'bollywood-movie'
        if movie.category != category:
            Movie.objects.filter(pk=movie.pk).update(category=category)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0018_separate_bollywood_categories'),
    ]

    operations = [
        migrations.RunPython(fix_bollywood_nigeria_overlap, migrations.RunPython.noop),
    ]