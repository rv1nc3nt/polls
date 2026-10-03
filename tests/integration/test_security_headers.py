# SPDX-License-Identifier: 0BSD
"""Browser-facing security headers (review A-10, decision log #44)."""

from __future__ import annotations

from django.test import Client, override_settings

from apps.core.headers import CONTENT_SECURITY_POLICY


def test_every_page_carries_the_policy(client: Client, db: None) -> None:
    for url in ("/fr/", "/fr/mairie/connexion/", "/fr/aide/", "/sante", "/fr/nulle-part/"):
        response = client.get(url)
        assert response["Content-Security-Policy"] == CONTENT_SECURITY_POLICY, url
        assert "camera=()" in response["Permissions-Policy"], url
        assert response["Cross-Origin-Resource-Policy"] == "same-origin", url


def test_the_policy_admits_nothing_inline_and_one_frame_origin() -> None:
    directives = dict(d.split(" ", 1) for d in CONTENT_SECURITY_POLICY.split("; "))
    for name in ("default-src", "script-src", "style-src", "img-src"):
        assert directives[name] == "'self'", name
    assert "unsafe" not in CONTENT_SECURITY_POLICY
    assert directives["frame-src"] == "https://www.youtube-nocookie.com"
    assert directives["frame-ancestors"] == "'none'"


@override_settings(CSP_REPORT_ONLY=True)
def test_report_only_is_a_way_back(client: Client, db: None) -> None:
    response = client.get("/fr/")
    assert response["Content-Security-Policy-Report-Only"] == CONTENT_SECURITY_POLICY
    assert "Content-Security-Policy" not in response
