from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0004_savedmovie'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DownloadJob',
            fields=[
                ('id', models.CharField(max_length=64, primary_key=True, serialize=False)),
                ('session_key', models.CharField(blank=True, db_index=True, max_length=40)),
                ('video_url', models.URLField(max_length=500)),
                ('download_format', models.CharField(max_length=30)),
                ('status', models.CharField(choices=[('starting', 'Starting'), ('downloading', 'Downloading'), ('pausing', 'Pausing'), ('paused', 'Paused'), ('cancelling', 'Cancelling'), ('complete', 'Complete'), ('error', 'Error')], default='starting', max_length=20)),
                ('progress', models.PositiveSmallIntegerField(default=0)),
                ('detail', models.CharField(blank=True, max_length=255)),
                ('filename', models.CharField(blank=True, max_length=255)),
                ('path', models.CharField(blank=True, max_length=500)),
                ('output_dir', models.CharField(blank=True, max_length=500)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ('-created_at',)},
        ),
    ]