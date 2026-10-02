# SPDX-License-Identifier: 0BSD
"""INV-1 against time (decision log #42), and the trend that no longer needs it.

A first ballot is cast from the page the voter confirmed their mailbox on,
minutes later, so any record of when — or merely in which order — ballots were
cast would pair them with registrations. None remains: no time column, no
insertion-ordered rowid, no confirmation instant, session expiries to the day.

The trend (R-11.5 bis) records each point the moment it falls due instead; the
tests below are the rules ``tests/unit/test_trend.py`` once checked against a
timeline of ballot versions, now checked against the points as written.
"""

from __future__ import annotations

from datetime import date, time, timedelta

import pytest
from django.db import IntegrityError, connection, transaction
from django.test import override_settings
from django.utils import timezone

from apps.audit.models import Reason
from apps.backoffice import trend as screen
from apps.ballots import services as ballots
from apps.ballots import trendpoints
from apps.ballots.models import Ballot, BallotSource, BallotStatus, TrendSnapshot
from apps.core.codes import new_tracking_code
from apps.core.crypto import new_token, voter_hash
from apps.core.sessions import SessionStore
from apps.core.types import OptionId, TokenSalt
from apps.elections.models import Poll
from apps.elections.transitions import close_poll
from apps.registrations.models import Registration, RegistrationState
from tests.conftest import force_open

ABC = [["a"], ["b"], ["c"]]
BCA = [["b"], ["c"], ["a"]]
DAY = date(2026, 9, 1)


@pytest.fixture
def poll(open_window_poll: Poll) -> Poll:
    return force_open(open_window_poll)


def _cast(poll: Poll, ranking: list[list[str]], n: int = 1, *, on: date = DAY) -> list[Ballot]:
    """``n`` first casts, as ``services`` writes them: the current epoch, then
    the point check, in the same breath."""
    out = []
    for _ in range(n):
        out.append(
            Ballot.objects.create(
                poll=poll,
                tracking_code=new_tracking_code(),
                ranking=ranking,
                source=BallotSource.ONLINE,
                epoch=trendpoints.current_epoch(poll),
            )
        )
        trendpoints.record_due_point(poll, today=on)
    return out


def _modify(poll: Poll, ballot: Ballot, ranking: list[list[str]]) -> Ballot:
    """A new version keeping the code and the epoch, as ``services.modify``."""
    Ballot.objects.filter(pk=ballot.pk).update(status=BallotStatus.SUPERSEDED)
    new = Ballot.objects.create(
        poll=poll,
        tracking_code=ballot.tracking_code,
        version=ballot.version + 1,
        ranking=ranking,
        source=BallotSource.ONLINE,
        epoch=ballot.epoch,
    )
    trendpoints.record_due_point(poll, today=DAY)
    return new


def _counts(poll: Poll) -> list[int]:
    return [p.ballot_count for p in screen.series(Poll.objects.get(pk=poll.pk))]


# --- nothing dates or orders a ballot ------------------------------------------


def test_a_ballot_records_no_time() -> None:
    kinds = {type(f).__name__ for f in Ballot._meta.get_fields()}
    assert not kinds & {"DateTimeField", "DateField", "TimeField"}, kinds


def test_the_ballots_table_keeps_no_insertion_order(db: None) -> None:
    """An ordinary SQLite table keeps a ``rowid`` in insertion order beside its
    primary key; this one is ``WITHOUT ROWID``, stored by random UUID. A later
    migration that rebuilds the table the Django way would bring it back."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT sql FROM sqlite_master WHERE name = 'ballots_ballot'")
        (sql,) = cursor.fetchone()
        assert sql.rstrip().endswith("WITHOUT ROWID"), sql
        with pytest.raises(Exception, match="rowid"):
            cursor.execute("SELECT rowid FROM ballots_ballot")


def test_a_session_expires_at_a_midnight(db: None) -> None:
    """A voter's session is saved as they cast; its exact expiry would date
    the ballot."""
    session = SessionStore()
    session["receipt:x"] = {"tracking_code": "AAAAAAAAAA"}
    session.save()
    row = session.model.objects.get(session_key=session.session_key)
    assert row.expire_date.timetz().replace(tzinfo=None) == time(0, 0)
    assert row.expire_date > timezone.now() + timedelta(days=13)


# --- points are taken as ballots are written ------------------------------------


def test_casting_the_tenth_ballot_takes_a_point(poll: Poll) -> None:
    """Through ``services.cast_online``, the real write path."""
    salt = TokenSalt(bytes(poll.token_salt))
    for k in range(10):
        token = new_token()
        Registration.objects.create(
            poll=poll,
            declared_last_name="X",
            declared_first_names="Y",
            email=f"v{k}@example.fr",
            email_canonical=f"v{k}@example.fr",
            state=RegistrationState.ACTIVE,
            voter_hash=voter_hash(salt, token),
        )
        assert TrendSnapshot.objects.filter(poll=poll).count() == 0
        ballots.cast_online(poll, token, ABC)
    (point,) = TrendSnapshot.objects.filter(poll=poll)
    assert (point.sequence, point.ballot_count) == (1, 10)
    assert point.orderings == [{"ranking": [["a"], ["b"], ["c"]], "count": 10}]
    assert sorted(set(Ballot.objects.filter(poll=poll).values_list("epoch", flat=True))) == [0]


def test_a_point_every_ten_shown_once_five_more_follow(poll: Poll) -> None:
    """10 appears at the 15th ballot, 20 at the 25th, 30 at the 35th."""
    expected = {15: [10], 24: [10], 25: [10, 20], 34: [10, 20], 35: [10, 20, 30]}
    for cast in range(1, 36):
        _cast(poll, ABC)
        if cast in expected:
            assert _counts(poll) == expected[cast], cast
    assert _counts(Poll.objects.get(pk=poll.pk)) == [10, 20, 30]


def test_too_few_ballots_show_nothing_while_open(poll: Poll) -> None:
    _cast(poll, ABC, 14)
    assert _counts(poll) == []


def test_a_modification_adds_no_ballot_and_reveals_nothing(poll: Poll) -> None:
    """Points count ballots, and a later version keeps its first cast's epoch:
    one elector modifying again and again neither cuts a point nor counts
    towards the five that show one (R-7.1)."""
    (x,) = _cast(poll, ABC)
    _cast(poll, ABC, 14)
    for ranking in (BCA, ABC) * 5:
        x = _modify(poll, x, ranking)
    assert x.epoch == 0
    assert TrendSnapshot.objects.filter(poll=poll).count() == 1
    assert _counts(poll) == [10]
    _cast(poll, ABC, 4)  # 19 ballots: point 20 not yet due
    assert TrendSnapshot.objects.filter(poll=poll).count() == 1


def test_a_shown_point_never_changes(poll: Poll) -> None:
    """Recomputing from the current live set would drop a modified ballot's
    old version from past points, and the difference would be that ballot."""
    (x,) = _cast(poll, ABC)
    _cast(poll, ABC, 19)
    before = screen.series(Poll.objects.get(pk=poll.pk))[0]
    _modify(poll, x, BCA)
    after = screen.series(Poll.objects.get(pk=poll.pk))[0]
    assert before == after
    assert after.pairwise[OptionId("a")][OptionId("b")] == 10


def test_a_written_point_cannot_be_changed_or_removed(poll: Poll) -> None:
    _cast(poll, ABC, 10)
    point = TrendSnapshot.objects.get(poll=poll)
    with pytest.raises(IntegrityError, match="R-11.5 bis"), transaction.atomic():
        TrendSnapshot.objects.filter(pk=point.pk).update(ballot_count=11)
    with pytest.raises(IntegrityError, match="R-11.5 bis"), transaction.atomic():
        TrendSnapshot.objects.filter(pk=point.pk).delete()


def test_once_closed_the_final_standing_follows_the_points_shown(poll: Poll) -> None:
    """Point 20 has only 3 ballots after it: never shown, since the published
    result minus it would be those 3 ballots."""
    _cast(poll, ABC, 23)
    close_poll(poll, early_reason=Reason.ADMINISTRATIVE_DECISION)
    poll.refresh_from_db()
    points = screen.series(poll)
    assert [(p.sequence, p.ballot_count) for p in points] == [(1, 10), (2, 23)]


def test_a_ballot_that_stops_counting_leaves_the_final_standing(poll: Poll) -> None:
    """A paper entry deleted, or awaiting countersignature."""
    (p, *_) = _cast(poll, ABC, 10)
    Ballot.objects.filter(pk=p.pk).update(status=BallotStatus.DELETED)
    close_poll(poll, early_reason=Reason.ADMINISTRATIVE_DECISION)
    poll.refresh_from_db()
    assert screen.series(poll)[-1].ballot_count == 9


def test_points_carry_the_day_they_were_taken(poll: Poll) -> None:
    _cast(poll, ABC, 15, on=DAY)
    _cast(poll, BCA, 25, on=DAY + timedelta(days=1))
    with override_settings(TREND_POLL_IDS=frozenset({poll.pk})):
        points = screen.series(Poll.objects.get(pk=poll.pk))
    assert [(p.sequence, p.through) for p in points] == [
        (1, DAY),
        (2, DAY + timedelta(days=1)),
        (3, DAY + timedelta(days=1)),
    ]
