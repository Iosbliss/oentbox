from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0011_normalize_foreign_movies'),
    ]

    operations = [
        migrations.AlterField(
            model_name='scraperun',
            name='status',
            field=models.CharField(choices=[('running', 'Running'), ('completed', 'Completed'), ('failed', 'Failed'), ('cancelled', 'Cancelled')], max_length=20),
        ),
        migrations.AddField(
            model_name='scraperun',
            name='process_id',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]