# SPDX-License-Identifier: 0BSD
"""config/formats/en/formats.py pins English to a 24-hour clock so a session
whose active language is English never shows an am/pm time — see that
module's docstring for why French alone getting this right is not enough."""

from __future__ import annotations

import datetime

from django.template.defaultfilters import date as date_filter
from django.utils import translation


def test_english_datetime_format_is_24_hour() -> None:
    noon = datetime.datetime(2026, 9, 20, 12, 0)
    afternoon = datetime.datetime(2026, 9, 20, 16, 30)
    with translation.override("en"):
        assert date_filter(noon, "DATETIME_FORMAT") == "Sept. 20, 2026, 12:00"
        assert date_filter(afternoon, "DATETIME_FORMAT") == "Sept. 20, 2026, 16:30"
        assert date_filter(afternoon, "TIME_FORMAT") == "16:30"


def test_french_datetime_format_is_still_24_hour() -> None:
    afternoon = datetime.datetime(2026, 9, 20, 16, 30)
    with translation.override("fr"):
        assert date_filter(afternoon, "DATETIME_FORMAT") == "20 septembre 2026 16:30"
