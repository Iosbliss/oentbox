from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import DownloadJob


class Command(BaseCommand):
    help = 'Remove expired download records and temporary output directories.'

    def add_arguments(self, parser):
        parser.add_argument('--hours', type=int, default=24)

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(hours=options['hours'])
        jobs = DownloadJob.objects.filter(updated_at__lt=cutoff).exclude(
            status__in={'starting', 'downloading', 'pausing', 'cancelling'},
        )
        count = 0
        for job in jobs:
            if job.output_dir:
                from pathlib import Path
                output_dir = Path(job.output_dir)
                for file in output_dir.glob('*'):
                    file.unlink(missing_ok=True)
                try:
                    output_dir.rmdir()
                except OSError:
                    pass
            job.delete()
            count += 1
        self.stdout.write(self.style.SUCCESS(f'Removed {count} expired download jobs.'))
