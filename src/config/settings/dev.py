# SPDX-License-Identifier: 0BSD
from .base import *
from .base import BASE_DIR

DEBUG = True
SECRET_KEY = "dev-only-not-a-secret"  # noqa: S105
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "var" / "dev.sqlite3",
        "OPTIONS": {"init_command": "PRAGMA foreign_keys=ON;"},
    }
}
