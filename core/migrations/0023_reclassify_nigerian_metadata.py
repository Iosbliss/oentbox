from django.db import migrations


def reclassify_nigerian_metadata(apps, schema_editor):
    Movie = apps.get_model('core', 'Movie')
    for movie in Movie.objects.all().iterator():
        metadata = movie.video_info or {}
        country = str(metadata.get('Country', '')).lower()
        text = f'{movie.title} {movie.description}'.lower()
        if 'nigeria' not in country and not any(
            marker in text for marker in ('nollywood', 'nigerian', 'naija', 'bbnaija', 'big brother naija')
        ):
            continue
        series = any(marker in text for marker in ('season', 'episode', 'series', 'tv series'))
        category = 'nollywood-tv-series' if series else 'nollywood-movie'
        if movie.category != category:
            Movie.objects.filter(pk=movie.pk).update(category=category)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0022_fix_render_category_mismatches'),
    ]

    operations = [
        migrations.RunPython(reclassify_nigerian_metadata, migrations.RunPython.noop),
    ]
