from django.db import migrations


def normalize_category_slugs(apps, schema_editor):
    Movie = apps.get_model('core', 'Movie')
    aliases = {
        'nollywood': 'nollywood-movie',
        'hollywood': 'hollywood-movie',
        'tv-series': 'hollywood-tv-series',
        'hollywood-movies': 'hollywood-movie',
        'hollywood-series': 'hollywood-tv-series',
        'nollywood-movies': 'nollywood-movie',
        'nollywood-series': 'nollywood-tv-series',
    }
    for old_category, new_category in aliases.items():
        Movie.objects.filter(category=old_category).update(category=new_category)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0013_widen_movie_urls'),
    ]

    operations = [
        migrations.RunPython(normalize_category_slugs, migrations.RunPython.noop),
    ]