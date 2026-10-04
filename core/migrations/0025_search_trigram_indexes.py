from django.contrib.postgres.indexes import GinIndex
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0024_newsletteremail_delete_downloadjob'),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS pg_trgm;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AddIndex(
            model_name='movie',
            index=GinIndex(name='movie_title_trgm', fields=['title'], opclasses=['gin_trgm_ops']),
        ),
        migrations.AddIndex(
            model_name='movie',
            index=GinIndex(name='movie_desc_trgm', fields=['description'], opclasses=['gin_trgm_ops']),
        ),
    ]
