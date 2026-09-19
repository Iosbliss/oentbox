from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0006_downloadjob_progress_controls'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='scraperun',
            constraint=models.UniqueConstraint(
                condition=models.Q(status='running'),
                fields=('status',),
                name='core_scraperun_one_running',
            ),
        ),
    ]
