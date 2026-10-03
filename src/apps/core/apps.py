# SPDX-License-Identifier: 0BSD
from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    label = "core"

    def ready(self) -> None:
        # Connects the sign-in signal (review A-16).
        from . import operatorsession  # noqa: F401
