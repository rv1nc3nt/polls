# SPDX-License-Identifier: 0BSD
"""WSGI entry point, served by gunicorn behind nginx (§14, §15). Defaults to
production settings, unlike ``manage.py``."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
application = get_wsgi_application()
