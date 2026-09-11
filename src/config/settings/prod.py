# SPDX-License-Identifier: 0BSD
"""Production settings. Every value of consequence comes from the environment
file rendered by Ansible (§15); nothing is defaulted to a working value here —
the one exception is the SMTP relay, which screen 12 (§6.5.12) can supply
instead, so its env vars are optional rather than required."""

import os

from .base import *

# The fallback ConfigurableEmailBackend uses while no admin has saved SMTP
# settings on screen 12 (§6.5.12) — the same env vars this used to be the
# whole of. DJANGO_EMAIL_HOST is no longer required at start-up: a commune
# that configures the relay entirely from the back-office needs none of these,
# and one that already sets them through Ansible is unaffected.
EMAIL_FALLBACK_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("DJANGO_EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("DJANGO_EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("DJANGO_EMAIL_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("DJANGO_EMAIL_PASSWORD", "")
EMAIL_USE_TLS = True

# nginx terminates TLS and sets these (§14); secure cookies and rate limiting
# both misbehave if they are not honoured.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o
]

# §14: rate limiting must count across workers, so the cache is shared. The
# database backend needs `manage.py createcachetable`, which the deploy runs.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "polls_cache",
    }
}

PUBLIC_BASE_URL = os.environ["DJANGO_PUBLIC_BASE_URL"]
