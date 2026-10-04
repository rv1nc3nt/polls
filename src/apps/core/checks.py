# SPDX-License-Identifier: 0BSD
"""System checks of this project's own (review A-2).

Django's ``security.W003`` looks for its own CSRF middleware by name and so
warns about ``BallotRouteCsrfMiddleware``, which subclasses it (decision log
#50). The settings silence W003 so that ``check --deploy`` can fail CI on any
warning; this check takes its place, so removing CSRF protection altogether is
still caught, now as an error and in every environment.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.apps import AppConfig
from django.conf import settings
from django.core.checks import CheckMessage, Error, Tags, register

CSRF_MIDDLEWARE = "apps.core.csrf.BallotRouteCsrfMiddleware"


@register(Tags.security)
def csrf_middleware_installed(
    app_configs: Sequence[AppConfig] | None, **kwargs: Any
) -> list[CheckMessage]:
    """Error unless the project's CSRF middleware is in ``MIDDLEWARE``."""
    if CSRF_MIDDLEWARE in settings.MIDDLEWARE:
        return []
    return [
        Error(
            f"{CSRF_MIDDLEWARE} is not in MIDDLEWARE: no form is protected against CSRF.",
            hint="It replaces django.middleware.csrf.CsrfViewMiddleware; restore it.",
            id="core.E001",
        )
    ]
