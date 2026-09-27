#!/usr/bin/env python3
"""Leak guard: fail if anything sensitive is present in the web-served static directory."""
import os
import sys

ROOT = "/opt/oentbox/staticfiles"
BAD_SUFFIXES = (
    ".py", ".pyc", ".sqlite", ".sqlite3", ".db", ".bak", ".log", ".pem",
    ".key", ".crt", ".p12", ".sh", ".sql", ".yml", ".yaml", ".toml", ".ini", ".conf",
)
BAD_NAMES = {
    ".env", ".env.example", ".env.local", "db.sqlite3", "manage.py", "settings.py",
    "requirements.txt", "credentials.txt", "id_rsa", "id_ed25519", "authorized_keys",
    "oentbox-superuser-credentials.txt",
}
BAD_DIRS = {
    "__pycache__", "migrations", "config", "core", "scraper", "ops",
    "templates", ".git", ".ssh", ".venv", ".kilo",
}
# Django's own admin static tree is collected under staticfiles/admin and is legitimate.
ALLOW_PREFIXES = (os.path.normpath("/opt/oentbox/staticfiles/admin"),)

found = []
if not os.path.isdir(ROOT):
    print("FAIL staticfiles directory %s is missing" % ROOT)
    sys.exit(1)

for dirpath, dirnames, filenames in os.walk(ROOT):
    normalized = os.path.normpath(dirpath)
    if any(normalized == p or normalized.startswith(p + os.sep) for p in ALLOW_PREFIXES):
        continue
    for d in list(dirnames):
        if d in BAD_DIRS or d.startswith("."):
            found.append(os.path.join(dirpath, d) + "/")
    for f in filenames:
        if f in BAD_NAMES or f.lower().endswith(BAD_SUFFIXES) or f.startswith("."):
            found.append(os.path.join(dirpath, f))

if found:
    print("FAIL %d sensitive path(s) present in %s:" % (len(found), ROOT))
    for p in found[:40]:
        print("  " + p)
    sys.exit(1)

print("OK   no sensitive files in %s" % ROOT)
sys.exit(0)
