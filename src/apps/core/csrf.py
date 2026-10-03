# SPDX-License-Identifier: 0BSD
"""Django's CSRF middleware, accepting ``Origin: null`` on the ballot routes.

R-7.4 ter has the ballot routes send ``Referrer-Policy: no-referrer``
(``tokensession.protect``), so the token in their address cannot travel in a
``Referer``. Under that policy the Fetch standard makes a browser send
``Origin: null`` with a form's POST, even to the same site, and Django refuses
any POST whose ``Origin`` is not the site's own: in a real browser no ballot
could be cast or modified. The HTTP tests never saw it, because Django's test
client sends no ``Origin`` at all; the browser test found it (review C-8,
decision log #50).

So on the ballot routes, and nowhere else, ``null`` is accepted as the origin.
That is no weaker than it sounds: the CSRF token is still checked, and it is a
secret another site cannot read; the CSRF cookie is ``SameSite=Lax``, so a
cross-site POST arrives without it; and any other ``Origin``, another site's
included, is refused as before.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, override

from django.http import HttpRequest, HttpResponseBase, HttpResponseForbidden
from django.middleware.csrf import CsrfViewMiddleware


class BallotRouteCsrfMiddleware(CsrfViewMiddleware):
    """``CsrfViewMiddleware``, with the one exception of the module docstring."""

    @override
    def process_view(
        self,
        request: HttpRequest,
        callback: Callable[..., HttpResponseBase],
        callback_args: tuple[Any, ...],
        callback_kwargs: dict[str, Any],
    ) -> HttpResponseForbidden | None:
        """Read a ballot route's ``Origin: null`` as the site's own origin, then
        check as Django does. ``get_host`` still holds the host to
        ``ALLOWED_HOSTS``; nothing else about the request changes."""
        match = request.resolver_match
        if (
            request.META.get("HTTP_ORIGIN") == "null"
            and match is not None
            and match.namespace == "ballots"
        ):
            request.META["HTTP_ORIGIN"] = f"{request.scheme}://{request.get_host()}"
        return super().process_view(request, callback, callback_args, callback_kwargs)
