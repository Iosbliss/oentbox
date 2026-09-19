import json
import os
from datetime import datetime

from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


def import_catalog(apps, schema_editor):
    Movie = apps.get_model('core', 'Movie')
    path = os.path.join(settings.BASE_DIR, 'scraper', 'movies.json')
    if not os.path.exists(path):
        return
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            records = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return
    for record in records:
        movie_id = str(record.get('id') or '').strip()
        link = str(record.get('link') or '').strip()
        title = str(record.get('title') or '').strip()
        if not movie_id or not link or not title:
            continue
        scraped_at = record.get('scraped_at') or '1970-01-01 00:00:00'
        try:
            scraped_at = datetime.strptime(scraped_at, '%Y-%m-%d %H:%M:%S')
        except (TypeError, ValueError):
            scraped_at = datetime(1970, 1, 1)
        scraped_at = timezone.make_aware(scraped_at, timezone.get_default_timezone())
        Movie.objects.update_or_create(
            id=movie_id,
            defaults={
                'title': title[:500], 'description': record.get('description', ''),
                'thumbnail': record.get('thumbnail', ''), 'link': link,
                'year': record.get('year'), 'category': record.get('category', 'unknown'),
                'source': record.get('source', '9jarocks'), 'scraped_at': scraped_at,
                'video_info': record.get('video_info') or {},
                'trailer_url': record.get('trailer_url', ''),
                'trailer_embed_url': record.get('trailer_embed_url', ''),
                'trailer_title': record.get('trailer_title', ''),
                'download_links': record.get('download_links') or [],
                'download_help_url': record.get('download_help_url', ''),
                'screenshots': record.get('screenshots') or [],
            },
        )


class Migration(migrations.Migration):
    dependencies = [('core', '0002_scraperun')]
    operations = [
        migrations.CreateModel(
            name='Movie',
            fields=[
                ('id', models.CharField(max_length=255, primary_key=True, serialize=False)),
                ('title', models.CharField(db_index=True, max_length=500)),
                ('description', models.TextField(blank=True)),
                ('thumbnail', models.URLField(blank=True)),
                ('link', models.URLField(unique=True)),
                ('year', models.PositiveIntegerField(blank=True, db_index=True, null=True)),
                ('category', models.CharField(db_index=True, max_length=100)),
                ('source', models.CharField(default='9jarocks', max_length=100)),
                ('scraped_at', models.DateTimeField(db_index=True)),
                ('video_info', models.JSONField(blank=True, default=dict)),
                ('trailer_url', models.URLField(blank=True)),
                ('trailer_embed_url', models.URLField(blank=True)),
                ('trailer_title', models.CharField(blank=True, max_length=500)),
                ('download_links', models.JSONField(blank=True, default=list)),
                ('download_help_url', models.CharField(blank=True, max_length=500)),
                ('screenshots', models.JSONField(blank=True, default=list)),
            ],
            options={'ordering': ('-scraped_at', 'title')},
        ),
        migrations.AddIndex(model_name='movie', index=models.Index(fields=['category', 'scraped_at'], name='core_movie_categor_3a37e4_idx')),
        migrations.AddIndex(model_name='movie', index=models.Index(fields=['title', 'year'], name='core_movie_title_4cf2dd_idx')),
        migrations.RunPython(import_catalog, migrations.RunPython.noop),
    ]