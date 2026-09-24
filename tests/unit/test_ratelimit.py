# SPDX-License-Identifier: 0BSD
"""Which address the rate limiter keys on behind the proxy (R-5.8, review note M3).

nginx sets ``X-Forwarded-For`` with ``$proxy_add_x_forwarded_for``, which
*appends* the address it saw to whatever the client sent. Only entries a
trusted proxy wrote can be believed, so the limiter counts from the right.
"""

from __future__ import annotations

import pytest
from django.test import RequestFactory, override_settings

from apps.core.ratelimit import client_digest

_PROXIED = {"SECURE_PROXY_SSL_HEADER": ("HTTP_X_FORWARDED_PROTO", "https")}


def _digest(forwarded: str | None, remote: str = "127.0.0.1") -> str:
    request = RequestFactory().get("/")
    request.META["REMOTE_ADDR"] = remote
    if forwarded is not None:
        request.META["HTTP_X_FORWARDED_FOR"] = forwarded
    return client_digest(request)


@override_settings(**_PROXIED, TRUSTED_PROXY_HOPS=1)
def test_a_forged_leading_entry_does_not_change_the_key() -> None:
    """The M3 bypass: a fresh forged header per request must not buy a fresh
    bucket, nor land the caller in a victim's."""
    honest = _digest("198.51.100.4")
    assert _digest("203.0.113.9, 198.51.100.4") == honest
    assert _digest("192.0.2.1, 203.0.113.9, 198.51.100.4") == honest
    assert _digest("198.51.100.4") != _digest("203.0.113.9")


@override_settings(**_PROXIED, TRUSTED_PROXY_HOPS=2)
def test_a_second_proxy_is_counted_from_the_right() -> None:
    """A CDN in front of nginx: the CDN appends the client, nginx the CDN."""
    client = _digest("198.51.100.4, 192.0.2.50")
    assert _digest("203.0.113.9, 198.51.100.4, 192.0.2.50") == client
    assert _digest("198.51.100.5, 192.0.2.50") != client


@override_settings(**_PROXIED, TRUSTED_PROXY_HOPS=2)
def test_fewer_entries_than_hops_uses_the_leftmost() -> None:
    """No client can shorten the header, so the leftmost of too few entries is
    still one a trusted proxy wrote."""
    assert _digest("198.51.100.4") == _digest("198.51.100.4, 192.0.2.50")


@pytest.mark.parametrize("forwarded", [None, "", " , "])
@override_settings(**_PROXIED)
def test_no_usable_header_falls_back_to_the_socket(forwarded: str | None) -> None:
    assert _digest(forwarded, remote="198.51.100.4") == _digest(None, remote="198.51.100.4")


@override_settings(SECURE_PROXY_SSL_HEADER=None)
def test_without_a_proxy_the_header_is_ignored() -> None:
    """Direct exposure (development): the header is entirely the client's."""
    assert _digest("203.0.113.9", remote="198.51.100.4") == _digest(None, remote="198.51.100.4")
