# Deployment checklist

1. Create a virtual environment and install `requirements.txt`.
2. Set the variables in `.env.example` in the process environment.
	Use `DJANGO_SECURE_SSL_REDIRECT=False` for the plain-HTTP Django development server and `True` only behind HTTPS in production.
3. Run `python manage.py migrate` and `python manage.py collectstatic --noinput`.
4. Create a staff account with `python manage.py createsuperuser`.
5. Run Django behind a production WSGI server such as Gunicorn or Waitress and a reverse proxy with HTTPS.
6. Keep the scraper as a scheduled management command until a real job queue is installed.
7. Install browser smoke-test dependencies with `playwright install chromium` after installing `requirements.txt`.

The current dashboard thread is suitable for local development only. For multiple workers or reliable long-running scrapes, add Celery/RQ with Redis and move the task state into the database or queue backend. Do not rely on process-local `SCRAPE_STATE` in production.

Run the checks before deployment:

```text
python manage.py check --deploy
python manage.py test
```

The browser smoke tests run as part of `python manage.py test` when Playwright's Chromium browser is installed; otherwise they are skipped.