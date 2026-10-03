# SPDX-License-Identifier: 0BSD
"""The project's own system checks (review A-2).

``security.W003`` is silenced because it misses the CSRF middleware subclass;
``core.E001`` stands in for it, so CSRF protection cannot be dropped unnoticed.
"""

from __future__ import annotations

from django.conf import settings
from django.core.checks import Error, run_checks
from django.test import override_settings

from apps.core.checks import CSRF_MIDDLEWARE, csrf_middleware_installed


def test_the_installed_middleware_passes() -> None:
    assert CSRF_MIDDLEWARE in settings.MIDDLEWARE
    assert csrf_middleware_installed(None) == []


def test_removing_csrf_protection_is_an_error() -> None:
    without = [m for m in settings.MIDDLEWARE if m != CSRF_MIDDLEWARE]
    with override_settings(MIDDLEWARE=without):
        errors = [m for m in run_checks() if m.id == "core.E001"]
    assert len(errors) == 1
    assert isinstance(errors[0], Error)


def test_django_own_csrf_warning_is_the_one_silenced() -> None:
    assert "security.W003" in settings.SILENCED_SYSTEM_CHECKS
