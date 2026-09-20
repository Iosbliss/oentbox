from django.db import migrations


def reclassify_catalog_categories(apps, schema_editor):
    from core.movie_data import classify_movie_category

    Movie = apps.get_model('core', 'Movie')
    for movie in Movie.objects.all().iterator():
        metadata = movie.video_info or {}
        category = classify_movie_category(
            movie.title,
            movie.description,
            movie.category,
            metadata,
        )
        if movie.category != category:
            Movie.objects.filter(pk=movie.pk).update(category=category)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0015_reclassify_nigerian_titles'),
    ]

    operations = [
        migrations.RunPython(reclassify_catalog_categories, migrations.RunPython.noop),
    ]