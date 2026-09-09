# SPDX-License-Identifier: 0BSD
"""The voting-window comparison across a daylight-saving transition (§4, T-47).

``check_ballot_window`` and ``check_registration_window`` compare two aware
datetimes with ``<`` / ``>=``. T-47 is that this resolves to the *absolute
instant*: around the Europe/Paris autumn fold the wall-clock reading ``02:30``
occurs twice, an hour apart in real time, and a ballot bearing the second one
must fall after a close set on the first.

The subtlety this pins: Python compares two aware datetimes that carry the
*same* ``ZoneInfo`` in wall-clock terms and ignores ``fold`` while doing so.
The application never hits that case — ``Poll.closes_at`` is read back from the
database UTC-aware and ``timezone.now()`` is UTC-aware, so both operands are
already absolute — and this test works in the same UTC instants to prove the
comparison the app actually performs is the correct one.

Pure: the polls here are never saved, and the clock is passed in explicitly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from apps.ballots.models import BallotSource
from apps.elections.models import Poll
from apps.elections.windows import WindowClosed, check_ballot_window, check_registration_window

PARIS = ZoneInfo("Europe/Paris")


def _utc(wall: datetime, *, fold: int) -> datetime:
    """The UTC instant of a Europe/Paris wall-clock reading — the form the
    application stores and compares in."""
    return wall.replace(tzinfo=PARIS, fold=fold).astimezone(UTC)


# Europe/Paris, 2025: clocks go back at 03:00 CEST → 02:00 CET on 26 October, so
# local 02:30 happens twice — first at UTC+2 (00:30 UTC), then at UTC+1 (01:30
# UTC).
_WALL_0230 = datetime(2025, 10, 26, 2, 30)
FIRST_0230 = _utc(_WALL_0230, fold=0)
SECOND_0230 = _utc(_WALL_0230, fold=1)


def _poll(closes_at: datetime) -> Poll:
    """An unsaved poll opened well before ``closes_at``, no deferred paper
    window."""
    return Poll(
        opens_at=closes_at - timedelta(days=1),
        closes_at=closes_at,
        paper_entry_deadline=closes_at,
    )


def test_the_two_readings_of_0230_are_a_real_hour_apart() -> None:
    assert FIRST_0230 == datetime(2025, 10, 26, 0, 30, tzinfo=UTC)
    assert SECOND_0230 == datetime(2025, 10, 26, 1, 30, tzinfo=UTC)
    assert SECOND_0230 - FIRST_0230 == timedelta(hours=1)


def test_t47_online_window_closes_on_the_absolute_instant_not_the_wall_clock() -> None:
    poll = _poll(FIRST_0230)

    # A minute before the close, first time round the clock: still open.
    check_ballot_window(poll, BallotSource.ONLINE, now=FIRST_0230 - timedelta(minutes=1))

    # 02:00 the *second* time round reads earlier on the wall clock than the
    # 02:30 close, but is 01:00 UTC — half an hour past it. Refused.
    second_0200 = _utc(datetime(2025, 10, 26, 2, 0), fold=1)
    assert second_0200 > FIRST_0230
    with pytest.raises(WindowClosed):
        check_ballot_window(poll, BallotSource.ONLINE, now=second_0200)

    # The same wall-clock 02:30, second time round: also refused.
    with pytest.raises(WindowClosed):
        check_ballot_window(poll, BallotSource.ONLINE, now=SECOND_0230)

    # One second past the close, exactly (mirrors T-3, across the fold).
    with pytest.raises(WindowClosed):
        check_ballot_window(poll, BallotSource.ONLINE, now=FIRST_0230 + timedelta(seconds=1))


def test_t47_registration_window_uses_the_same_absolute_comparison() -> None:
    poll = _poll(FIRST_0230)
    check_registration_window(poll, now=FIRST_0230 - timedelta(minutes=1))
    with pytest.raises(WindowClosed):
        check_registration_window(poll, now=SECOND_0230)


def test_t47_paper_deadline_after_the_fold_keeps_keying_open_through_it() -> None:
    """A deferred paper deadline set to the *second* 02:30 leaves the keying
    window open at the first one and shut at the second — again the absolute
    instants, an hour apart (§6.4)."""
    poll = Poll(
        opens_at=FIRST_0230 - timedelta(days=1),
        closes_at=FIRST_0230,
        paper_entry_deadline=SECOND_0230,
    )
    # Online voting is shut at the first 02:30…
    with pytest.raises(WindowClosed):
        check_ballot_window(poll, BallotSource.ONLINE, now=FIRST_0230 + timedelta(seconds=1))
    # …but paper keying runs until the second one.
    check_ballot_window(poll, BallotSource.PAPER, now=FIRST_0230 + timedelta(seconds=1))
    with pytest.raises(WindowClosed):
        check_ballot_window(poll, BallotSource.PAPER, now=SECOND_0230)


def test_t47_spring_forward_gap_reading_is_still_a_definite_instant() -> None:
    """30 March 2025, 02:00 CET → 03:00 CEST: local 02:30 does not occur.
    ``astimezone`` still resolves it to one instant, and the comparison holds."""
    gap = _utc(datetime(2025, 3, 30, 2, 30), fold=0)
    poll = _poll(gap)
    check_ballot_window(poll, BallotSource.ONLINE, now=gap - timedelta(minutes=1))
    with pytest.raises(WindowClosed):
        check_ballot_window(poll, BallotSource.ONLINE, now=gap + timedelta(minutes=1))
