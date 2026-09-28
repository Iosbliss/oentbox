from django.db import migrations


def fix_nigerian_subject_classification(apps, schema_editor):
    Movie = apps.get_model('core', 'Movie')
    for movie in Movie.objects.filter(title__icontains='Bob Hearts Abishola'):
        movie.category = 'hollywood-tv-series'
        movie.save(update_fields=['category'])


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0020_reclassify_wura'),
    ]

    operations = [
        migrations.RunPython(fix_nigerian_subject_classification, migrations.RunPython.noop),
    ]