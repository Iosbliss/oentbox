from config.celery import app


@app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={'max_retries': 2})
def run_download_job_task(self, job_id):
    from .views import _run_youtube_download

    _run_youtube_download(job_id)
