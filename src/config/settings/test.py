# SPDX-License-Identifier: 0BSD
from .base import *

DEBUG = False
SECRET_KEY = "test-only-not-a-secret"  # noqa: S105
ALLOWED_HOSTS = ["testserver", "localhost"]
# The fallback ConfigurableEmailBackend uses while no test has saved a
# MailSettings row (§6.5.12); django.test.Client / pytest-django read the
# outbox this backend fills exactly as before screen 12 existed.
EMAIL_FALLBACK_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
# In-memory is fine for the trigger tests of §5.1: raw SQL goes through the
# same connection as the ORM, so the triggers are present and firing.
DATABASES["default"]["NAME"] = ":memory:"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
