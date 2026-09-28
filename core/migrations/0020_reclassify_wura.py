from django.db import migrations


def reclassify_wura(apps, schema_editor):
    Movie = apps.get_model('core', 'Movie')
    for movie in Movie.objects.filter(title__icontains='wura'):
        movie.category = 'nollywood-tv-series'
        movie.save(update_fields=['category'])


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0019_fix_bollywood_nigeria_overlap'),
    ]

    operations = [
        migrations.RunPython(reclassify_wura, migrations.RunPython.noop),
    ]