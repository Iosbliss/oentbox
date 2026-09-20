from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0012_scraperun_process_id'),
    ]

    operations = [
        migrations.AlterField(
            model_name='movie',
            name='thumbnail',
            field=models.URLField(blank=True, max_length=500),
        ),
        migrations.AlterField(
            model_name='movie',
            name='link',
            field=models.URLField(max_length=500, unique=True),
        ),
        migrations.AlterField(
            model_name='movie',
            name='trailer_url',
            field=models.URLField(blank=True, max_length=500),
        ),
        migrations.AlterField(
            model_name='movie',
            name='trailer_embed_url',
            field=models.URLField(blank=True, max_length=500),
        ),
    ]