from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import Movie, ScrapeRun


class Command(BaseCommand):
    help = 'Run a scraper job and persist its outcome.'

    def add_arguments(self, parser):
        parser.add_argument('--run-id', type=int, required=True)

    def handle(self, *args, **options):
        run = ScrapeRun.objects.get(pk=options['run_id'])
        started_count = run.total_titles
        try:
            call_command('scrape_movies', auto=True, max_pages=500)
            finished_count = Movie.objects.count()
            run.status = 'completed'
            run.total_titles = finished_count
            run.new_titles = max(0, finished_count - started_count)
        except Exception as error:
            run.status = 'failed'
            run.error = str(error)
            raise CommandError(str(error))
        finally:
            run.finished_at = timezone.now()
            run.save(update_fields=['status', 'total_titles', 'new_titles', 'error', 'finished_at'])