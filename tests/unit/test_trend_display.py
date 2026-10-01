# SPDX-License-Identifier: 0BSD
"""The trend screen's geometry (R-11.5 bis): axis rounding and the spacing of
the curves' end labels. No database: the helpers take plain values."""

from __future__ import annotations

from apps.backoffice.trend import _axis, _spread


def test_the_axis_always_holds_zero_on_round_ticks() -> None:
    assert _axis([12.0, 33.3]) == (0, 40, 10)
    assert _axis([-36.6, 8.9]) == (-40, 10, 10)
    assert _axis([-100.0, 33.3]) == (-100, 50, 25)


def test_a_flat_series_still_gets_a_visible_range() -> None:
    lo, hi, _step = _axis([0.0])
    assert lo < 0 < hi


def test_end_labels_are_pushed_apart_in_order() -> None:
    assert _spread([100, 105, 300]) == [100, 116, 300]
    assert _spread([50, 50, 50]) == [50, 66, 82]
