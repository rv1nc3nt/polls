# SPDX-License-Identifier: 0BSD
"""The current page's address in another language, for the ballot pages'
language links (decision log #51).

Everywhere else the language switcher is a form posted to ``set_language``.
On a ballot page that cannot work: the page sends no referrer (R-7.4 ter), so
the browser posts with ``Origin: null``, which the CSRF check accepts on the
ballot routes alone (``core/csrf.py``), not on ``set_language``. A link to the
same page under the other language prefix needs no form, and stays on a ballot
route, which nginx does not log.
"""

from __future__ import annotations

from django import template
from django.urls import translate_url

register = template.Library()


@register.filter
def in_language(path: str, language: str) -> str:
    """``path``, a path of this site, as it reads in ``language``."""
    return translate_url(path, language)
