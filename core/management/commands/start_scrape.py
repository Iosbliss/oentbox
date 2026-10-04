from django.core.management.base import BaseCommand
from django.db import close_old_connections

from core.models import Movie, ScrapeRun


class Command(BaseCommand):
    help = 'Start one catalog scrape run (used by cron).'

    def handle(self, *args, **options):
        close_old_connections()
        if ScrapeRun.objects.filter(status='running').exists():
            self.stdout.write('A scrape run is already active; skipping.')
            return

        started_count = Movie.objects.count()
        run = ScrapeRun.objects.create(status='running', total_titles=started_count)

        import subprocess
        import sys
        import tempfile
        from pathlib import Path

        log_path = Path(tempfile.gettempdir()) / f'oentbox-scrape-{run.pk}.log'
        project_root = Path(__file__).resolve().parents[3]
        with log_path.open('ab') as handle:
            worker = subprocess.Popen(
                [sys.executable, str(project_root / 'manage.py'),
                 'run_scrape_job', '--run-id', str(run.pk)],
                cwd=str(project_root),
                stdout=handle,
                stderr=subprocess.STDOUT,
                close_fds=True,
                start_new_session=True,
            )
        ScrapeRun.objects.filter(pk=run.pk).update(process_id=worker.pid)
        self.stdout.write(f'Scrape run {run.pk} started (pid {worker.pid}, log {log_path}).')
