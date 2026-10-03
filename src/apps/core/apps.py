# SPDX-License-Identifier: 0BSD
from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    label = "core"

    def ready(self) -> None:
        # Connects the sign-in signal (review A-16) and registers the system
        # checks (review A-2).
        from . import checks, operatorsession  # noqa: F401
