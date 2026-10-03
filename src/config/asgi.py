# SPDX-License-Identifier: 0BSD
"""The ASGI entry point. Production runs the WSGI one under gunicorn
(§14); this exists for a server that wants ASGI."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
application = get_asgi_application()
