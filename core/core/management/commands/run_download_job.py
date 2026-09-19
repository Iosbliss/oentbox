from django.core.management.base import BaseCommand, CommandError

from core.views import _run_youtube_download


class Command(BaseCommand):
    help = 'Run one persisted YouTube download job outside the web worker.'

    def add_arguments(self, parser):
        parser.add_argument('--job-id', required=True)

    def handle(self, *args, **options):
        try:
            _run_youtube_download(options['job_id'])
        except Exception as error:
            raise CommandError(str(error)) from error