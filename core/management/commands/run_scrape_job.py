from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import Movie, ScrapeRun
from core.management.commands.scrape_movies import set_progress_callback


class Command(BaseCommand):
    help = 'Run a scraper job and persist its outcome.'

    def add_arguments(self, parser):
        parser.add_argument('--run-id', type=int, required=True)

    def handle(self, *args, **options):
        run = ScrapeRun.objects.get(pk=options['run_id'])
        started_count = run.total_titles

        def save_progress(message, current, total):
            ScrapeRun.objects.filter(pk=run.pk, status='running').update(
                progress_message=message,
                progress_current=max(0, current),
                progress_total=max(0, total),
            )

        try:
            set_progress_callback(save_progress)
            call_command('scrape_movies', auto=True, max_pages=500)
            finished_count = Movie.objects.count()
            run.status = 'completed'
            run.total_titles = finished_count
            run.new_titles = max(0, finished_count - started_count)
            run.progress_current = finished_count
            run.progress_total = finished_count
            run.progress_message = 'Scrape complete'
        except Exception as error:
            run.status = 'failed'
            run.error = str(error)
            run.progress_message = 'Scrape failed'
            raise CommandError(str(error))
        finally:
            run.finished_at = timezone.now()
            if run.status in {'running', 'failed'}:
                run.save(update_fields=[
                    'status', 'total_titles', 'new_titles', 'progress_current',
                    'progress_total', 'progress_message', 'error', 'finished_at',
                ])
            set_progress_callback(None)