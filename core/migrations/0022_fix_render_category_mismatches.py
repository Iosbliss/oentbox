from django.db import migrations


def fix_known_category_mismatches(apps, schema_editor):
    Movie = apps.get_model('core', 'Movie')

    # These records were saved before the category-specific scraper rules and
    # were being reclassified only in some read paths.
    Movie.objects.filter(title__startswith='Wu Assassins Season 1').update(
        category='korean-drama',
    )
    Movie.objects.filter(title__startswith='Asterix: The Secret of the Magic Potion').update(
        category='anime',
    )


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0021_fix_nigerian_subject_classification'),
    ]

    operations = [
        migrations.RunPython(fix_known_category_mismatches, migrations.RunPython.noop),
    ]
