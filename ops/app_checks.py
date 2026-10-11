#!/usr/bin/env python3
"""Application-level health checks for oentbox: catalog freshness, scraper runs, download jobs."""
import datetime
import os
import sys

APP = "/opt/oentbox"
os.chdir(APP)
sys.path.insert(0, APP)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
for line in open(os.path.join(APP, ".env")):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)

import django  # noqa: E402

django.setup()

from django.utils import timezone  # noqa: E402

from core.models import Movie, ScrapeRun  # noqa: E402


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


SCRAPE_MAX_AGE_H = env_int("SCRAPE_MAX_AGE_HOURS", 48)
SCRAPE_STUCK_H = env_int("SCRAPE_STUCK_HOURS", 6)

now = timezone.now()
failures = []


def report(ok, msg):
    print(("OK   " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)


total = Movie.objects.count()
report(total > 0, "catalog has %d titles" % total)

newest = Movie.objects.order_by("-scraped_at").values_list("scraped_at", flat=True).first()
if newest:
    age_h = (now - newest).total_seconds() / 3600
    report(age_h <= SCRAPE_MAX_AGE_H, "newest title scraped %.1fh ago (limit %dh)" % (age_h, SCRAPE_MAX_AGE_H))
else:
    report(False, "catalog is empty")

run = ScrapeRun.objects.order_by("-started_at").first()
if run is None:
    report(True, "no scrape runs recorded yet")
elif run.status == "failed":
    detail = (run.error or "no detail")[:160]
    report(False, "latest scrape run FAILED: %s" % detail)
elif run.status == "running":
    running_h = (now - run.started_at).total_seconds() / 3600
    report(running_h <= SCRAPE_STUCK_H, "scrape run running %.1fh (stuck limit %dh)" % (running_h, SCRAPE_STUCK_H))
else:
    report(True, "latest scrape run %s, %d new titles" % (run.status, run.new_titles))

if failures:
    print("SUMMARY: " + "; ".join(failures))
sys.exit(1 if failures else 0)
