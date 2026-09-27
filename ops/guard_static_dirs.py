#!/usr/bin/env python3
"""Guard: STATICFILES_DIRS must never include the project root itself.

Including BASE_DIR makes collectstatic publish the whole project (the database,
settings, manage.py, source) into the web-served staticfiles directory.
Paths derived from BASE_DIR such as BASE_DIR / "static" are fine.
"""
import ast
import re
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "/opt/oentbox/config/settings.py"

try:
    src = open(path).read()
except OSError as exc:
    print("FAIL cannot read %s: %s" % (path, exc))
    sys.exit(1)

match = re.search(r"^STATICFILES_DIRS\s*=\s*(.+?)\s*$", src, re.M)
if not match:
    print("FAIL STATICFILES_DIRS not found in %s" % path)
    sys.exit(1)

expr = match.group(1).strip()
try:
    node = ast.parse(expr, mode="eval").body
except SyntaxError as exc:
    print("FAIL cannot parse STATICFILES_DIRS expression %r: %s" % (expr, exc))
    sys.exit(1)

if not isinstance(node, (ast.List, ast.Tuple)):
    print("FAIL STATICFILES_DIRS is not a literal list/tuple: %s" % expr)
    sys.exit(1)

bad = []
for elt in node.elts:
    # bare BASE_DIR (or list(BASE_DIR) / str(BASE_DIR)) points at the project root
    if isinstance(elt, ast.Name) and elt.id == "BASE_DIR":
        bad.append("BASE_DIR")
    elif isinstance(elt, ast.Call) and elt.args:
        arg = elt.args[0]
        if isinstance(arg, ast.Name) and arg.id == "BASE_DIR":
            bad.append("BASE_DIR")

if bad:
    print(
        "FAIL STATICFILES_DIRS includes the project root (%s) in %s: %s - remove it so "
        "collectstatic cannot publish the database and source code" % (", ".join(bad), path, expr)
    )
    sys.exit(1)

print("OK   STATICFILES_DIRS = %s (%s)" % (expr, path))
sys.exit(0)
