#!/usr/bin/env python3
"""Pre-warm the local poster cache.

Renders the busiest pages, collects every /img?u=... optimiser URL and builds
those images locally, so visitors get nginx-served WebP files immediately
instead of triggering the fetch themselves.
"""
import os
import re
import sys
import time
import urllib.parse

APP = "/opt/oentbox"
os.chdir(APP)
sys.path.insert(0, APP)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
for line in open(os.path.join(APP, ".env")):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value)

import django  # noqa: E402

django.setup()

from django.test import Client  # noqa: E402

from core import imageproxy  # noqa: E402

PAGES = (
    "/",
    "/browse.html?cat=all",
    "/browse.html?cat=nollywood-movie",
    "/browse.html?cat=hollywood-movie",
)
PATTERN = re.compile(r"/img\?u=([^\"'&]+)&(?:amp;)?w=(\d+)")
LIMIT = int(os.environ.get("WARM_IMAGE_LIMIT", "400"))


def main():
    client = Client(HTTP_HOST="oentbox.com")
    seen = {}
    for page in PAGES:
        response = client.get(page, secure=True)
        if response.status_code != 200:
            print("  skip %s (HTTP %s)" % (page, response.status_code))
            continue
        body = response.content.decode("utf-8", "replace")
        for encoded, width in PATTERN.findall(body):
            seen[urllib.parse.unquote(encoded)] = int(width)
        print("  %-40s %d image reference(s)" % (page, len(PATTERN.findall(body))))

    targets = list(seen.items())[:LIMIT]
    print("warming %d unique image(s)..." % len(targets))
    started = time.time()
    built = failed = 0
    for url, width in targets:
        if imageproxy.ensure_cached(url, width):
            built += 1
        else:
            failed += 1
    print(
        "done in %.1fs: %d built, %d failed, %.1f MB in %s"
        % (
            time.time() - started,
            built,
            failed,
            sum(
                os.path.getsize(os.path.join(imageproxy.CACHE_DIR, name))
                for name in os.listdir(imageproxy.CACHE_DIR)
                if name.endswith(".webp")
            )
            / (1024.0 * 1024.0)
            if os.path.isdir(imageproxy.CACHE_DIR)
            else 0.0,
            imageproxy.CACHE_DIR,
        )
    )
    return 0 if built or not targets else 1


if __name__ == "__main__":
    sys.exit(main())
