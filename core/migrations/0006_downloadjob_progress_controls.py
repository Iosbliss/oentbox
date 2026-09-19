from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0005_downloadjob'),
    ]

    operations = [
        migrations.AddField(
            model_name='downloadjob',
            name='cancel_requested',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='downloadjob',
            name='downloaded_bytes',
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='downloadjob',
            name='eta',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='downloadjob',
            name='speed',
            field=models.FloatField(default=0),
        ),
        migrations.AddField(
            model_name='downloadjob',
            name='stop_requested',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='downloadjob',
            name='total_bytes',
            field=models.BigIntegerField(default=0),
        ),
    ]