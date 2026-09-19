from django.db import migrations


def normalize_foreign_movies(apps, schema_editor):
    Movie = apps.get_model('core', 'Movie')
    markers = (
        'bollywood', 'indian', 'hindi', 'tamil', 'telugu', 'bengali', 'marathi',
        'punjabi', 'pakistani', 'spanish', 'french', 'german', 'italian',
        'arabic', 'indonesian', 'malaysian', 'russian', 'vietnamese', 'portuguese',
    )
    for movie in Movie.objects.filter(category__in={'hollywood-movie', 'hollywood-tv-series'}).iterator():
        metadata = f'{movie.title} {movie.description or ""} {movie.video_info or ""}'.lower()
        if not any(marker in metadata for marker in markers):
            continue
        category = 'other-foreign-series' if movie.category == 'hollywood-tv-series' else 'foreign-movie'
        Movie.objects.filter(pk=movie.pk).update(category=category)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0010_normalize_movie_categories'),
    ]

    operations = [migrations.RunPython(normalize_foreign_movies, migrations.RunPython.noop)]