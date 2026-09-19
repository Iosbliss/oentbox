from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0008_activityevent_youtube_types'),
    ]

    operations = [
        migrations.AddField(
            model_name='scraperun',
            name='progress_current',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='scraperun',
            name='progress_message',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='scraperun',
            name='progress_total',
            field=models.PositiveIntegerField(default=0),
        ),
    ]