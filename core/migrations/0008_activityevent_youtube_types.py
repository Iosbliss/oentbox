from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0007_scraperun_one_running'),
    ]

    operations = [
        migrations.AlterField(
            model_name='activityevent',
            name='event_type',
            field=models.CharField(
                max_length=30,
                choices=[
                    ('download', 'Download'),
                    ('trailer_watch', 'Trailer watch'),
                    ('youtube_search', 'YouTube search'),
                    ('youtube_download', 'YouTube download'),
                ],
            ),
        ),
    ]
