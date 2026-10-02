# SPDX-License-Identifier: 0BSD
"""The browser-facing security headers Django's ``SecurityMiddleware`` does not
set (review A-10, decision log #44).

**Content-Security-Policy.** The pages render operator Markdown and embed
YouTube; the sanitiser (``elections.richtext``) is the first defence and this
is the second, should anything get past it. Everything comes from this origin
— no CDN, no inline script, no inline style, no event-handler attribute — so
the policy can be strict; the one third party is the YouTube embed's frame.
A test fails if a template brings back an inline script, style or handler.

**Permissions-Policy** turns off the device features nothing here uses, so an
embedded frame cannot ask for them either. **Cross-Origin-Resource-Policy**
keeps other sites from embedding this one's responses.

Set in Django, not nginx, so every deployment gets them, the hand-installed
ones of ``contrib/init/`` included. Not under ``DEBUG``: Django's own error
page styles itself inline. ``CSP_REPORT_ONLY`` sends the policy as
``Content-Security-Policy-Report-Only`` instead — a way back, should a browser
refuse something the tests did not foresee.
"""

from __future__ import annotations

from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse

CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self'",
        "font-src 'self'",
        "connect-src 'self'",
        # elections.richtext builds the only iframe, from a validated id.
        "frame-src https://www.youtube-nocookie.com",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)

PERMISSIONS_POLICY = ", ".join(
    f"{feature}=()"
    for feature in (
        "camera",
        "microphone",
        "geolocation",
        "payment",
        "usb",
        "serial",
        "bluetooth",
        "browsing-topics",
    )
)


class SecurityHeadersMiddleware:
    """Adds the headers of the module docstring to every response, outside
    ``DEBUG``, without replacing one a view set itself."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """The response, with the headers added unless already present."""
        response = self.get_response(request)
        if settings.DEBUG:
            return response
        header = (
            "Content-Security-Policy-Report-Only"
            if settings.CSP_REPORT_ONLY
            else "Content-Security-Policy"
        )
        response.headers.setdefault(header, CONTENT_SECURITY_POLICY)
        response.headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        return response
