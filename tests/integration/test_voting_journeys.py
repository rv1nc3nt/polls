# SPDX-License-Identifier: 0BSD
"""Whole voting journeys on a poll that reached ``open`` the way a real one does.

Every other voting test builds its poll with ``force_open`` or a past-dated
draft (see ``tests/conftest.py``), which skips ``announce_poll``/``open_poll``
altogether. That is right for a test about something else, and it is why two
regressions got through: an elector whose paper ballot was deleted could not
come back online (R-9.4 against R-5.9), and nothing proved a poll forced open
by hand could be voted on at once (R-3.4). What is pinned here is the elector's
side, over HTTP, from a poll opened by the real transitions — and each journey
runs unchanged on a sandbox poll, since what works for a real poll must work
for a rehearsal (R-3.7).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from django.core import mail as django_mail
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client
from django.test.utils import override_settings
from django.utils import timezone

from apps.audit.models import Reason
from apps.backoffice import dashboard, review
from apps.ballots import services as ballots
from apps.ballots.models import Ballot, BallotStatus
from apps.core.models import User
from apps.elections import closure, sharelink
from apps.elections.models import Poll, PollOption, PollState, RollEntry, WorkingRollEntry
from apps.elections.transitions import announce_poll, open_poll
from apps.publicsite import views as publicsite_views
from apps.registrations import services as registrations
from apps.registrations.models import Channel, Registration, RegistrationState
from tests.conftest import force_announce

CaptureOnCommit = Callable[..., AbstractContextManager[list[Any]]]

FORM = {
    "last_name": "Dupont",
    "first_names": "Émile",
    "date_of_birth": "12/05/1970",
    "email": "emile.dupont@example.fr",
    "declared_on_honour": "on",
}
STRICT = {"order": "a,b,c", "rank_a": "1", "rank_b": "2", "rank_c": "3"}
RANKING = [["a"], ["b"], ["c"]]

#: A real poll and a sandbox poll take the same journey.
KINDS = pytest.mark.parametrize("sandbox", [False, True], ids=["real", "sandbox"])
#: How the poll came to be open: forced by hand well ahead of ``opens_at``, or
#: by the scheduled job once ``opens_at`` had passed.
OPENINGS = pytest.mark.parametrize("opening", ["by_hand", "on_schedule"])


@pytest.fixture(autouse=True)
def _cache_and_roll(db: None) -> None:
    cache.clear()
    WorkingRollEntry.objects.create(
        birth_name="Dupont",
        first_names="Émile",
        date_of_birth="12/05/1970",
        date_of_birth_parsed="1970-05-12",
        list_types=["principale"],
    )


@pytest.fixture
def operator() -> User:
    return User.objects.create_user(username="op", password="x", full_name="Op Un")


def _opened_poll(
    *, sandbox: bool, opening: str = "by_hand", lock_dir: Path | None = None, **config: Any
) -> Poll:
    """A poll taken ``draft → announced → open`` the way a real one is.

    ``by_hand`` announces it with ``opens_at`` still in the future, as R-3.10
    requires, then forces it open at once (R-3.4). ``on_schedule`` runs the
    ``open_poll`` command on an announced poll whose ``opens_at`` has passed —
    the job as it runs in production, on time or late; the announcement is
    back-dated with ``force_announce`` because ``announce_poll`` refuses a past
    ``opens_at``. The clock is not faked: the INV-2 trigger reads the database's
    own, so a shifted Python clock would only make the two disagree.
    """
    now = timezone.now()
    scheduled = opening == "on_schedule"
    poll = Poll.objects.create(
        title_i18n={"fr": "Aménagement de la place"},
        description_i18n={"fr": "Trois propositions."},
        languages=["fr"],
        opens_at=now - timedelta(minutes=5) if scheduled else now + timedelta(hours=6),
        closes_at=now + timedelta(days=3),
        paper_entry_deadline=now + timedelta(days=3),
        is_sandbox=sandbox,
        **config,
    )
    for position, option_id in enumerate(["a", "b", "c"]):
        PollOption.objects.create(
            poll=poll, option_id=option_id, label_i18n={"fr": option_id.upper()}, position=position
        )
    if scheduled:
        assert lock_dir is not None
        force_announce(poll)
        with override_settings(JOB_LOCK_DIR=lock_dir):
            call_command("open_poll")
    else:
        announce_poll(poll)
        open_poll(Poll.objects.get(pk=poll.pk), now=now)
    poll = Poll.objects.get(pk=poll.pk)
    assert poll.state == PollState.OPEN
    return poll


def _enter(poll: Poll, operator: User) -> Client:
    """A browser at the poll's door: nothing to do for a real poll, the share
    link for a sandbox one (R-3.7)."""
    client = Client()
    if poll.is_sandbox:
        sharelink.generate(poll, actor=operator)
        poll.refresh_from_db()
        assert client.get(f"/fr/scrutin/{poll.pk}/apercu/{poll.preview_token}/").status_code == 200
    return client


def _register_over_http(
    client: Client, poll: Poll, capture: CaptureOnCommit, **over: str
) -> str | None:
    """Submit the registration form; return the token from the mailed link, or
    ``None`` when the form was refused (it re-renders with a 200, sends nothing)."""
    django_mail.outbox.clear()
    with capture(execute=True):
        response = client.post(f"/fr/inscription/{poll.pk}/", {**FORM, **over})
    if response.status_code == 200:
        assert not django_mail.outbox
        return None
    assert response.status_code == 302, response.content.decode()
    match = re.search(r"/bulletin/[0-9a-f-]+/acces/(\S+?)/", str(django_mail.outbox[-1].body))
    assert match, django_mail.outbox[-1].body
    return match.group(1)


def _access(poll: Poll, token: str) -> str:
    return f"/fr/bulletin/{poll.pk}/acces/{token}/"


def _cast(poll: Poll, token: str) -> None:
    """Follow the mailed link on another device and cast: no cookie, no share
    link — the token alone must be enough."""
    voter = Client()
    shown = voter.get(_access(poll, token))
    assert shown.status_code == 200, shown.content.decode()
    assert "Valider mon bulletin" in shown.content.decode()
    cast = voter.post(_access(poll, token), STRICT)
    assert cast.status_code == 302, cast.content.decode()
    assert voter.get(cast["Location"]).status_code == 200


def _entry(poll: Poll) -> RollEntry:
    return RollEntry.objects.get(poll=poll)


# --- R-3.4: a poll forced open is votable at once ----------------------------


@KINDS
@OPENINGS
def test_a_poll_opened_by_the_real_transitions_can_be_registered_on_and_voted(
    sandbox: bool,
    opening: str,
    operator: User,
    django_capture_on_commit_callbacks: CaptureOnCommit,
    tmp_path: Path,
) -> None:
    poll = _opened_poll(sandbox=sandbox, opening=opening, lock_dir=tmp_path)
    client = _enter(poll, operator)

    token = _register_over_http(client, poll, django_capture_on_commit_callbacks)
    assert token is not None
    _cast(poll, token)

    assert Ballot.live.filter(poll=poll).count() == 1
    assert Registration.objects.get(poll=poll).channel == Channel.ONLINE


@KINDS
def test_a_poll_forced_open_ahead_of_opens_at_can_then_be_modified(
    sandbox: bool,
    operator: User,
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    poll = _opened_poll(sandbox=sandbox, opening="by_hand")
    token = _register_over_http(_enter(poll, operator), poll, django_capture_on_commit_callbacks)
    assert token is not None
    _cast(poll, token)

    voter = Client()
    landed = voter.get(_access(poll, token))
    assert landed.status_code == 302  # to the token-free modification page
    page = voter.get(landed["Location"])
    assert page.status_code == 200
    changed = voter.post(
        landed["Location"], {"order": "a,b,c", "rank_a": "3", "rank_b": "2", "rank_c": "1"}
    )
    assert changed.status_code == 302
    (live,) = Ballot.live.filter(poll=poll)
    assert live.version == 2 and live.ranking == [["c"], ["b"], ["a"]]


# --- R-9.4: a deleted paper ballot re-opens online voting --------------------


@KINDS
def test_an_elector_registered_online_then_keyed_on_paper_votes_again_once_it_is_deleted(
    sandbox: bool,
    operator: User,
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    poll = _opened_poll(sandbox=sandbox)
    token = _register_over_http(_enter(poll, operator), poll, django_capture_on_commit_callbacks)
    assert token is not None
    paper = ballots.enter_paper(poll, str(_entry(poll).pk), RANKING, str(operator.pk), "fr")

    # While the paper ballot stands the link sends them to the mairie (R-9.2).
    assert Client().get(_access(poll, token)).status_code == 302
    ballots.delete_paper(paper, str(operator.pk), Reason.KEYING_ERROR, "")

    _cast(poll, token)
    assert Ballot.live.filter(poll=poll).count() == 1
    assert Ballot.objects.get(pk=paper.pk).status == BallotStatus.DELETED


@KINDS
def test_an_elector_whose_mail_was_never_opened_cannot_vote_online_once_keyed_on_paper(
    sandbox: bool,
    operator: User,
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    """A ``pending_email`` registration holds a token whose link has not been
    followed. Keying a paper ballot puts the elector on the ``paper`` channel; the
    link, followed afterwards, confirms the mailbox but must not open the ballot
    (R-9.1, R-9.2) — and, the paper ballot deleted, it must again (R-9.4)."""
    poll = _opened_poll(sandbox=sandbox)
    token = _register_over_http(_enter(poll, operator), poll, django_capture_on_commit_callbacks)
    assert token is not None
    assert Registration.objects.get(poll=poll).state == RegistrationState.PENDING_EMAIL
    paper = ballots.enter_paper(poll, str(_entry(poll).pk), RANKING, str(operator.pk), "fr")

    voter = Client()
    page = voter.get(_access(poll, token))
    assert page.status_code == 302 and page["Location"].endswith("/info/mairie/")
    posted = voter.post(_access(poll, token), STRICT)
    assert posted.status_code == 302 and posted["Location"].endswith("/info/mairie/")
    assert list(Ballot.live.filter(poll=poll)) == [paper]
    registration = Registration.objects.get(poll=poll)
    assert registration.channel == Channel.PAPER
    assert registration.state == RegistrationState.ACTIVE  # the link still proved the mailbox

    ballots.delete_paper(paper, str(operator.pk), Reason.KEYING_ERROR, "")
    _cast(poll, token)
    assert Registration.objects.get(poll=poll).channel == Channel.ONLINE


def test_a_paper_ballot_keyed_for_an_unconfirmed_registration_is_counted(
    operator: User, django_capture_on_commit_callbacks: CaptureOnCommit
) -> None:
    """The mail is never opened: the registration stays ``pending_email`` with a
    live paper ballot hanging off it — and must stay so through the transcription
    window, where the INV-2 trigger freezes ``state``. Every participation figure
    counts it as a paper voter, not as someone still to confirm, so the counts
    published at closure agree with the ballots they accompany (§9, decision log
    #29)."""
    poll = _opened_poll(sandbox=False, show_live_participation=True)
    token = _register_over_http(_enter(poll, operator), poll, django_capture_on_commit_callbacks)
    assert token is not None
    ballots.enter_paper(poll, str(_entry(poll).pk), RANKING, str(operator.pk), "fr")
    assert Registration.objects.get(poll=poll).state == RegistrationState.PENDING_EMAIL

    live = dashboard.participation(poll)
    assert (live.registered, live.voted_paper, live.not_voted, live.pending_email) == (1, 1, 0, 0)
    assert review.awaiting_confirmation(poll) == []
    assert publicsite_views._live_participation(poll) == {
        "voted_online": 0,
        "voted_paper": 1,
        "voted_total": 1,
        "not_voted": 0,
    }
    counts = closure.frozen_counts(poll)
    assert counts == {
        "registered": 1,
        "ballots_online": 0,
        "ballots_paper": 1,
        "paper_uncountersigned": 0,
        "non_voters": 0,
    }
    assert counts["ballots_paper"] == Ballot.live.filter(poll=poll).count()


@KINDS
def test_an_elector_keyed_on_paper_who_never_registered_can_register_and_vote_once_it_is_deleted(
    sandbox: bool,
    operator: User,
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    """The regression behind decision log #25, end to end: the form, the mail,
    the link and the cast — not only ``register()`` returning a token."""
    poll = _opened_poll(sandbox=sandbox)
    paper = ballots.enter_paper(poll, str(_entry(poll).pk), RANKING, str(operator.pk), "fr")
    ballots.delete_paper(paper, str(operator.pk), Reason.VOTER_REQUEST, "")

    client = _enter(poll, operator)
    token = _register_over_http(client, poll, django_capture_on_commit_callbacks)
    assert token is not None, "the form refused an elector whose paper ballot was deleted"
    _cast(poll, token)

    assert Registration.objects.filter(poll=poll).count() == 1
    assert Registration.objects.get(poll=poll).channel == Channel.ONLINE
    assert Ballot.live.filter(poll=poll).count() == 1


@KINDS
def test_a_live_paper_ballot_keeps_the_elector_from_registering_online_over_http(
    sandbox: bool,
    operator: User,
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    poll = _opened_poll(sandbox=sandbox)
    ballots.enter_paper(poll, str(_entry(poll).pk), RANKING, str(operator.pk), "fr")

    token = _register_over_http(_enter(poll, operator), poll, django_capture_on_commit_callbacks)
    # Refused on the form: no redirect, no mail.
    assert token is None
    assert Ballot.live.filter(poll=poll).count() == 1


@KINDS
def test_an_elector_sent_to_review_is_approved_and_votes_after_a_paper_ballot_was_deleted(
    sandbox: bool,
    operator: User,
    django_capture_on_commit_callbacks: CaptureOnCommit,
) -> None:
    """Same R-9.4 promise by the other door. A slightly different spelling of the
    name sends the application to review; the poll admin then binds it to the
    roll entry a deleted paper ballot left a cleared shell on. Approval must not
    refuse that entry as 'already registered' (R-5.9) any more than the form
    does."""
    poll = _opened_poll(sandbox=sandbox)
    paper = ballots.enter_paper(poll, str(_entry(poll).pk), RANKING, str(operator.pk), "fr")
    ballots.delete_paper(paper, str(operator.pk), Reason.KEYING_ERROR, "")

    client = _enter(poll, operator)
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            f"/fr/inscription/{poll.pk}/", {**FORM, "last_name": "Dupond-Martin"}
        )
    assert response.status_code == 302
    pending = Registration.objects.get(poll=poll, state=RegistrationState.PENDING_REVIEW)

    _registration, token = registrations.approve(
        pending, _entry(poll), Reason.IDENTITY_CONFIRMED_AT_MAIRIE, operator
    )
    _cast(poll, token.reveal())
    assert Ballot.live.filter(poll=poll).count() == 1


# --- The link once the window has closed -------------------------------------


@KINDS
def test_the_link_of_an_elector_who_has_not_voted_is_dead_once_online_voting_closes(
    sandbox: bool,
    operator: User,
    django_capture_on_commit_callbacks: CaptureOnCommit,
    tmp_path: Path,
) -> None:
    """Both the page and a cast posted from it are refused after ``closes_at``,
    on the clock and whatever ``Poll.state`` still says (INV-2, R-3.3)."""
    # Scheduled opening: ``opens_at`` is already behind us, so ``closes_at`` can move
    # into the past without breaking ``closes_at > opens_at``.
    poll = _opened_poll(sandbox=sandbox, opening="on_schedule", lock_dir=tmp_path)
    token = _register_over_http(_enter(poll, operator), poll, django_capture_on_commit_callbacks)
    assert token is not None
    # closes_at and paper_entry_deadline are the two settings that still move (R-3.4).
    ended = timezone.now() - timedelta(minutes=1)
    Poll.objects.filter(pk=poll.pk).update(closes_at=ended, paper_entry_deadline=ended)
    assert Poll.objects.get(pk=poll.pk).state == PollState.OPEN

    voter = Client()
    page = voter.get(_access(poll, token))
    assert page.status_code == 302 and page["Location"].endswith("/info/indisponible/")
    posted = voter.post(_access(poll, token), STRICT)
    assert posted.status_code == 302 and posted["Location"].endswith("/info/indisponible/")
    assert not Ballot.objects.filter(poll=poll).exists()
    assert Registration.objects.get(poll=poll).channel == Channel.NONE
