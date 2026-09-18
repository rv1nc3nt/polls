# SPDX-License-Identifier: 0BSD
"""R-7.4 ter: django.request must never write a ballot token to the log,
even on an unhandled exception nginx's own suppression cannot see."""

from __future__ import annotations

import logging

from apps.core.logging import REDACTED, RedactBallotTokenPath


class _Request:
    def __init__(self, path: str) -> None:
        self.path = path


def _record(path: str, *args: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="django.request",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="%s: %s",
        args=args,
        exc_info=None,
    )
    record.request = _Request(path)
    return record


def test_redacts_the_token_on_the_ballot_access_route() -> None:
    record = _record("/fr/bulletin/1234/acces/SECRETTOKEN/", "Internal Server Error", "ignored")
    assert RedactBallotTokenPath().filter(record) is True
    assert record.getMessage() == f"Internal Server Error: {REDACTED}"


def test_also_redacts_a_token_free_route_under_the_same_prefix() -> None:
    """Matches nginx's own suppression, which covers the whole ``/bulletin/``
    prefix rather than just ``acces/`` — deliberately, so a future
    token-bearing route under it cannot leak by omission
    (``nginx-vhost.conf.j2``)."""
    record = _record("/fr/bulletin/1234/recu/", "Internal Server Error", "/fr/bulletin/1234/recu/")
    RedactBallotTokenPath().filter(record)
    assert record.getMessage() == f"Internal Server Error: {REDACTED}"


def test_leaves_an_unrelated_route_alone() -> None:
    record = _record("/fr/inscription/1234/", "Internal Server Error", "/fr/inscription/1234/")
    RedactBallotTokenPath().filter(record)
    assert record.getMessage() == "Internal Server Error: /fr/inscription/1234/"


def test_tolerates_a_record_with_no_request() -> None:
    record = logging.LogRecord(
        name="django.server",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="%s",
        args=("no request attached",),
        exc_info=None,
    )
    assert RedactBallotTokenPath().filter(record) is True
