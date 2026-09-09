# SPDX-License-Identifier: 0BSD
"""Settings common to every environment.

Deployment renders an environment file (§15); nothing here reads a secret from
the repository.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]
SRC_DIR = BASE_DIR / "src"

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
DEBUG = False
ALLOWED_HOSTS: list[str] = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h]

# §14: no django.contrib.admin anywhere, in any environment. The back-office is
# purpose-built (§6.5) and the admin is precisely the tool that would let
# someone browse registrations and ballots side by side.
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.core",
    "apps.elections",
    "apps.registrations",
    "apps.ballots",
    "apps.audit",
    "apps.backoffice",
    "apps.publicsite",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [SRC_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
                # The commune record (§6.5.11) for the R-1.4 / R-13.2 notices.
                "apps.core.context.commune",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DJANGO_DB_PATH", BASE_DIR / "var" / "polls.sqlite3"),
        "OPTIONS": {
            # WAL mode (§14). Foreign keys and triggers carry the invariants of
            # §5.1, so both must be on for every connection.
            "init_command": (
                "PRAGMA journal_mode=WAL;"
                "PRAGMA foreign_keys=ON;"
                "PRAGMA synchronous=NORMAL;"
                "PRAGMA busy_timeout=5000;"
            ),
            "transaction_mode": "IMMEDIATE",
        },
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "core.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

# §14 Time. USE_TZ with an explicit Europe/Paris default; each poll also stores
# its own timezone (§3.1).
LANGUAGE_CODE = "fr"
LANGUAGES = [("fr", "Français"), ("en", "English")]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "var" / "static"
STATICFILES_DIRS = [SRC_DIR / "static"]

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"

# §6.5: the back-office is the only authenticated area, and it is reached by
# named accounts only (R-2.2). There is no self-service signup and no password
# reset by mail: accounts are created on screen 10 or by the first-run wizard.
LOGIN_URL = "backoffice:login"
LOGIN_REDIRECT_URL = "backoffice:poll_index"
LOGOUT_REDIRECT_URL = "backoffice:login"

DEFAULT_FROM_EMAIL = os.environ.get("DJANGO_FROM_EMAIL", "mairie@example.fr")

# Links in outgoing mail (§6.2 step 7). A management command sending reminders
# has no request to infer the host from, so the site's own address is
# deployment configuration (§15) rather than something derived per send.
PUBLIC_BASE_URL = os.environ.get("DJANGO_PUBLIC_BASE_URL", "http://localhost:8000")

# Rate limiting (R-5.8) counts through the cache. LocMem is per process, so it
# under-counts across gunicorn workers; production uses the database backend,
# which needs `manage.py createcachetable` at deploy (§15). No Redis: §14 keeps
# the dependencies few, and a commune-sized instance does not need one.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "polls",
    }
}

# R-5.8, as counts per window. Deferred to configuration rather than constants
# (§13): a commune with six thousand electors and one with sixty need different
# numbers, and neither should have to edit the source to get them.
RATE_LIMIT_REGISTRATION = os.environ.get("DJANGO_RATE_LIMIT_REGISTRATION", "5/1h")
RATE_LIMIT_EMAIL = os.environ.get("DJANGO_RATE_LIMIT_EMAIL", "3/1h")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    # §14: commands log to stdout/stderr, captured by whatever invoked them.
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("DJANGO_LOG_LEVEL", "INFO")},
}

# Application version, reported by GET /sante (§14).
APP_VERSION = os.environ.get("APP_VERSION", "0.1.0-dev")

# Directory holding job lock files (§14, self-locking commands).
JOB_LOCK_DIR = Path(os.environ.get("DJANGO_JOB_LOCK_DIR", BASE_DIR / "var" / "locks"))
