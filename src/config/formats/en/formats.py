# SPDX-License-Identifier: 0BSD
"""Overrides Django's built-in English format module, which uses a 12-hour
clock (``TIME_FORMAT = "P"``, e.g. "noon" / "4 p.m."). French's own built-in
module already renders 24-hour (``"H:i"``), and every visible time on this
platform goes through the locale-dependent ``DATETIME_FORMAT``/``TIME_FORMAT``
template filters (never a hardcoded format string) — so switching the active
language to English, on a page where most strings still fall back to their
French ``msgid`` for want of a translation, is the one way an am/pm time can
appear. Pinning English to 24-hour here keeps both languages consistent.

Every other constant (``DATE_FORMAT`` and so on) is left undefined and falls
through to Django's own English module — ``FORMAT_MODULE_PATH`` resolution
tries this module first, attribute by attribute, per Django's
``get_format_modules``.
"""

TIME_FORMAT = "H:i"
DATETIME_FORMAT = "N j, Y, H:i"
