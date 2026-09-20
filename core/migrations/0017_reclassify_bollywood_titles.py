from django.db import migrations


def reclassify_bollywood_titles(apps, schema_editor):
    from core.movie_data import classify_movie_category

    Movie = apps.get_model('core', 'Movie')
    for movie in Movie.objects.all().iterator():
        text = f'{movie.title} {movie.description}'.lower()
        if 'bollywood' not in text:
            continue
        category = classify_movie_category(
            movie.title,
            movie.description,
            movie.category,
            movie.video_info or {},
        )
        if movie.category != category:
            Movie.objects.filter(pk=movie.pk).update(category=category)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0016_reclassify_catalog_categories'),
    ]

    operations = [
        migrations.RunPython(reclassify_bollywood_titles, migrations.RunPython.noop),
    ]