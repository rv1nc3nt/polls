# SPDX-License-Identifier: 0BSD
"""Local development: ``manage.py`` defaults to these. SQLite under ``var/``,
mail printed to the console, a fixed non-secret key."""

import os

from .base import *
from .base import BASE_DIR, DATABASES

DEBUG = True
SECRET_KEY = "dev-only-not-a-secret"  # noqa: S105
# The first-run wizard's code on a development machine (README quick start).
SETUP_TOKEN = "dev"  # noqa: S105
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
# The fallback ConfigurableEmailBackend uses while screen 12 (§6.5.12) has no
# saved settings.
EMAIL_FALLBACK_BACKEND = "django.core.mail.backends.console.EmailBackend"
# Only the file differs from production: the OPTIONS (WAL, busy_timeout,
# IMMEDIATE transactions) are base's, so development runs with the same
# concurrency semantics (review note M4).
# DJANGO_DB_PATH points it elsewhere, as in production: the manual's captures
# are rendered from a throwaway demo database (docs/manuel/captures/README.md).
DATABASES = {
    "default": {
        **DATABASES["default"],
        "NAME": os.environ.get("DJANGO_DB_PATH", BASE_DIR / "var" / "dev.sqlite3"),
    }
}
