# SPDX-License-Identifier: 0BSD
"""Redacts ballot-token URLs from Django's own request logging (R-7.4 ter).

nginx suppresses ``access_log`` for the whole ``/<lang>/bulletin/`` prefix and
gunicorn is started with no ``--access-logfile`` of its own
(``ansible/roles/polls/templates/nginx-vhost.conf.j2``,
``polls.service.j2``), deliberately for the whole prefix rather than just
``acces/<token>/`` (``apps/ballots/urls.py``) so a future token-bearing route
under it cannot leak by omission. Neither covers Django's own logging: on any
unhandled exception under that prefix,
``django.core.handlers.exception.response_for_exception`` logs
``request.path`` at ERROR through the ``django.request`` logger regardless of
what the web server does. That path is caught here at the handler, not the
``django.request`` logger specifically, so any present or future logger that
attaches a ``request`` to a record is covered the same way.

The regex mirrors nginx's ``$polls_loggable`` map exactly, so the two
suppressions stay in step.
"""

from __future__ import annotations

import logging
import re

_TOKEN_PATH = re.compile(r"^/[a-z]{2}/bulletin/")
REDACTED = "[adresse supprimée : jeton de bulletin, R-7.4 ter]"


class RedactBallotTokenPath(logging.Filter):
    """Replaces a token-bearing ``request.path`` with a placeholder.

    Django's ``log_response`` always passes ``request.path`` as the final
    positional argument to the format string (``"%s: %s", ..., request.path``)
    and the request itself via ``extra={"request": request}`` — so the request
    object, not string-matching the rendered message, is what decides whether
    to redact.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        path = getattr(getattr(record, "request", None), "path", None)
        if isinstance(path, str) and _TOKEN_PATH.match(path) and record.args:
            args = record.args if isinstance(record.args, tuple) else (record.args,)
            record.args = (*args[:-1], REDACTED)
        return True
