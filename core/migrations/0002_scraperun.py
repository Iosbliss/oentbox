from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='ScrapeRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('started_at', models.DateTimeField(auto_now_add=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('status', models.CharField(choices=[('running', 'Running'), ('completed', 'Completed'), ('failed', 'Failed')], max_length=20)),
                ('new_titles', models.PositiveIntegerField(default=0)),
                ('total_titles', models.PositiveIntegerField(default=0)),
                ('error', models.TextField(blank=True)),
            ],
            options={'ordering': ('-started_at',)},
        ),
    ]