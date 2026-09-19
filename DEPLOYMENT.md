# Deployment checklist

1. Create a virtual environment and install `requirements.txt`.
2. Set the variables in `.env.example` in the process environment.
	Use `DJANGO_SECURE_SSL_REDIRECT=False` for the plain-HTTP Django development server and `True` only behind HTTPS in production.
3. Run `python manage.py migrate` and `python manage.py collectstatic --noinput`.
4. Create a staff account with `python manage.py createsuperuser`.
5. Run Django behind a production WSGI server such as Gunicorn or Waitress and a reverse proxy with HTTPS.
6. Run the scraper and download jobs through management commands so they are independent of Gunicorn worker lifetimes.
7. Install browser smoke-test dependencies with `playwright install chromium` after installing `requirements.txt`.

The scraper and download job state is persisted in the database. The web process starts short-lived management-command workers, so long-running work is not tied to a Gunicorn worker thread. For high-volume workloads, add Celery/RQ with Redis and move process supervision into that queue.

Run the checks before deployment:

```text
python manage.py check --deploy
python manage.py test
```

The browser smoke tests run as part of `python manage.py test` when Playwright's Chromium browser is installed; otherwise they are skipped.