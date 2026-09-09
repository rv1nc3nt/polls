# SPDX-License-Identifier: 0BSD
"""Template context available on every page.

The commune record (§6.5.11) carries the identity the public notices must show:
the data controller (R-13.1) and the data-protection referent (R-13.2). It is
``None`` until the first-run wizard has created it, and every template that
uses it falls back to a generic label so a not-yet-installed instance still
renders.
"""

from __future__ import annotations

from django.http import HttpRequest

from .models import Commune


def commune(request: HttpRequest) -> dict[str, Commune | None]:
    return {"commune": Commune.current()}
