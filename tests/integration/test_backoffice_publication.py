# SPDX-License-Identifier: 0BSD
"""Screen 9 of §6.5 over HTTP — clôture et publication.

The closure hash, the frozen counts and the tally are computed and tested in
``elections/closure`` and ``elections/transitions``; here it is the screen: that
the gate holds (poll admin only, §3.7), that the derivation is shown for a
closed poll and never for an open one, that the CSV and JSON artefacts are the
live set and the §9 document (§9, R-11.2), that publication goes through
``transitions.publish_poll`` and is logged, and that a ``physical`` tie-break
must be entered before publication is allowed (§8.3).

No elector identity appears on this screen: the counts are the ones frozen at
closure and the derivation is the pure tally, so there is nothing here to assert
the absence of a voter→ballot join against — there is no join to make.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.audit.models import Action, AuditEvent, Reason
from apps.ballots.models import Ballot, BallotSource
from apps.core.canonical import closure_hash
from apps.core.codes import new_tracking_code
from apps.core.models import PollRole, Role, User
from apps.elections.closure import live_ballots
from apps.elections.models import Poll, PollOption, PollState, TiebreakRule, WorkingRollEntry
from apps.elections.transitions import close_poll
from tests.conftest import force_open

CYCLE = (
    [["a"], ["b"], ["c"]],
    [["b"], ["c"], ["a"]],
    [["c"], ["a"], ["b"]],
)


@pytest.fixture
def admin_user(db: None) -> User:
    return User.objects.create_user(username="p.admin", password="x", full_name="P. Admin")


def _grant(poll: Poll, user: User, role: Role = Role.POLL_ADMIN) -> None:
    PollRole.objects.create(poll=poll, user=user, role=role)


def _url(poll: Poll) -> str:
    return f"/fr/mairie/scrutin/{poll.pk}/depouillement/"


def _make_poll(*, tiebreak: str = TiebreakRule.COMPUTED) -> Poll:
    now = timezone.now()
    poll = Poll.objects.create(
        title_i18n={"fr": "Aménagement"},
        description_i18n={"fr": "Trois propositions."},
        languages=["fr"],
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
        tiebreak_rule=tiebreak,
    )
    for position, option_id in enumerate(["a", "b", "c"]):
        PollOption.objects.create(
            poll=poll, option_id=option_id, label_i18n={"fr": option_id.upper()}, position=position
        )
    WorkingRollEntry.objects.create(
        birth_name="Dupont",
        first_names="Émile",
        date_of_birth="12/05/1970",
        date_of_birth_parsed="1970-05-12",
        list_types=["principale"],
    )
    return poll


def _cast(poll: Poll, rankings: object) -> None:
    for ranking in rankings:  # type: ignore[attr-defined]
        Ballot.objects.create(
            poll=poll,
            tracking_code=new_tracking_code(),
            ranking=ranking,
            source=BallotSource.ONLINE,
        )


@pytest.fixture
def closed_poll(admin_user: User) -> Poll:
    """A closed Schulze poll with a clear winner: two ballots, both a > b > c."""
    poll = _make_poll()
    force_open(poll)
    _cast(poll, ([["a"], ["b"], ["c"]], [["a"], ["b"], ["c"]]))
    close_poll(poll, early_reason=Reason.ADMINISTRATIVE_DECISION)
    _grant(poll, admin_user)
    return Poll.objects.get(pk=poll.pk)


@pytest.fixture
def tied_poll(admin_user: User) -> Poll:
    """A closed ``physical`` poll whose tally is a three-way Schulze tie."""
    poll = _make_poll(tiebreak=TiebreakRule.PHYSICAL)
    force_open(poll)
    _cast(poll, CYCLE)
    close_poll(poll, early_reason=Reason.ADMINISTRATIVE_DECISION)
    _grant(poll, admin_user)
    return Poll.objects.get(pk=poll.pk)


# --- the gate (§3.7) ---------------------------------------------------------


def test_an_entry_operator_cannot_reach_the_screen(
    client: Client, closed_poll: Poll, db: None
) -> None:
    """Publication is the poll admin's, not the entry operator's (§3.7)."""
    operator = User.objects.create_user(username="op.x", password="x", full_name="Op X")
    PollRole.objects.create(poll=closed_poll, user=operator, role=Role.ENTRY_OPERATOR)
    client.force_login(operator)
    assert client.get(_url(closed_poll)).status_code == 403


def test_an_auditor_reads_the_screen_but_cannot_publish(
    client: Client, closed_poll: Poll, db: None
) -> None:
    """R-2.1 names the anonymised ballot list among the auditor's read-only
    access, alongside the poll configuration and the audit log — this screen
    is where that list, and its CSV/JSON artefacts, actually live."""
    auditor = User.objects.create_user(username="aud.x", password="x", full_name="Aud X")
    PollRole.objects.create(poll=closed_poll, user=auditor, role=Role.AUDITOR)
    client.force_login(auditor)

    response = client.get(_url(closed_poll))
    assert response.status_code == 200
    assert response.context["can_act"] is False
    body = response.content.decode()
    assert 'name="action" value="publish"' not in body

    assert client.get(_url(closed_poll), {"format": "csv"}).status_code == 200
    assert client.get(_url(closed_poll), {"format": "json"}).status_code == 200
    assert (
        client.post(_url(closed_poll), {"confirmed": "1", "action": "publish"}).status_code == 403
    )


def test_the_poll_admin_sees_the_derivation(
    client: Client, closed_poll: Poll, admin_user: User
) -> None:
    client.force_login(admin_user)
    body = client.get(_url(closed_poll)).content.decode()
    assert closed_poll.closure_hash is not None
    assert bytes(closed_poll.closure_hash).hex() in body
    # winner label and the pairwise matrix caption
    assert "Matrice des préférences" in body
    assert "A" in body


def test_the_dashboard_links_to_the_screen(
    client: Client, closed_poll: Poll, admin_user: User
) -> None:
    client.force_login(admin_user)
    body = client.get(f"/fr/mairie/scrutin/{closed_poll.pk}/").content.decode()
    assert f"/mairie/scrutin/{closed_poll.pk}/depouillement/" in body


# --- before closure --------------------------------------------------------


def test_an_open_poll_shows_no_derivation(client: Client, admin_user: User) -> None:
    poll = _make_poll()
    force_open(poll)
    _grant(poll, admin_user)
    client.force_login(admin_user)

    body = client.get(_url(poll)).content.decode()
    assert "n'est pas encore clos" in body
    assert "Matrice des préférences" not in body


# --- the artefacts (§9, R-11.2) ------------------------------------------


def test_csv_is_exactly_the_live_set_and_recomputes_the_hash(
    client: Client, closed_poll: Poll, admin_user: User
) -> None:
    client.force_login(admin_user)
    response = client.get(_url(closed_poll) + "?format=csv")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")

    rows = [line for line in response.content.decode().splitlines() if line]
    assert rows[0] == "tracking_code,ranking"
    assert len(rows) == 1 + len(live_ballots(closed_poll))
    assert closed_poll.closure_hash is not None
    assert bytes(closed_poll.closure_hash) == closure_hash(live_ballots(closed_poll))


def test_json_is_the_publication_document(
    client: Client, closed_poll: Poll, admin_user: User
) -> None:
    client.force_login(admin_user)
    document = json.loads(client.get(_url(closed_poll) + "?format=json").content)
    assert closed_poll.closure_hash is not None
    assert document["closure_hash"] == bytes(closed_poll.closure_hash).hex()
    assert document["winner"] == "a"
    assert document["counts"] == closed_poll.frozen_counts


# --- publication ---------------------------------------------------------


def test_publish_transitions_the_poll_and_is_logged(
    client: Client, closed_poll: Poll, admin_user: User
) -> None:
    client.force_login(admin_user)
    # R-2.4, T-93: the first POST only states what publishing will do.
    page = client.post(_url(closed_poll), {"action": "publish"}).content.decode()
    assert "Publier les résultats ?" in page
    closed_poll.refresh_from_db()
    assert closed_poll.state == PollState.CLOSED

    response = client.post(_url(closed_poll), {"confirmed": "1", "action": "publish"})
    assert response.status_code == 302

    closed_poll.refresh_from_db()
    assert closed_poll.state == PollState.PUBLISHED
    assert AuditEvent.objects.filter(action=Action.RESULTS_PUBLISHED, poll=closed_poll).exists()
    assert AuditEvent.objects.filter(action=Action.TALLY_RUN, poll=closed_poll).exists()

    # The public results page is now reachable.
    assert client.get(f"/fr/scrutin/{closed_poll.pk}/resultats/").status_code == 200


def test_a_published_poll_is_read_only_with_download_links(
    client: Client, closed_poll: Poll, admin_user: User
) -> None:
    client.force_login(admin_user)
    client.post(_url(closed_poll), {"confirmed": "1", "action": "publish"})

    body = client.get(_url(closed_poll)).content.decode()
    assert "résultats sont publiés" in body
    assert "?format=csv" in body
    assert f"/fr/scrutin/{closed_poll.pk}/resultats/" in body


# --- physical tie-break (§8.3) -----------------------------------------


def test_publication_is_refused_while_the_physical_draw_is_unentered(
    client: Client, tied_poll: Poll, admin_user: User
) -> None:
    client.force_login(admin_user)
    body = client.get(_url(tied_poll)).content.decode()
    assert "tirage au sort physique" in body
    assert "Publier les résultats" not in body

    client.post(_url(tied_poll), {"confirmed": "1", "action": "publish"})
    tied_poll.refresh_from_db()
    assert tied_poll.state == PollState.CLOSED


def test_recording_the_draw_lets_publication_proceed(
    client: Client, tied_poll: Poll, admin_user: User
) -> None:
    client.force_login(admin_user)
    response = client.post(_url(tied_poll), {"action": "record_tiebreak", "order": ["b", "c", "a"]})
    assert response.status_code == 302

    tied_poll.refresh_from_db()
    assert tied_poll.physical_tiebreak_order == ["b", "c", "a"]
    event = AuditEvent.objects.get(action=Action.TIEBREAK_ENTERED, poll=tied_poll)
    assert event.after["order"] == ["b", "c", "a"]

    assert client.post(_url(tied_poll), {"confirmed": "1", "action": "publish"}).status_code == 302
    tied_poll.refresh_from_db()
    assert tied_poll.state == PollState.PUBLISHED

    document = json.loads(client.get(_url(tied_poll) + "?format=json").content)
    assert document["winner"] == "b"
    assert document["tiebreak"] == {
        "rule": "physical",
        "tied": ["a", "b", "c"],
        "order": ["b", "c", "a"],
        "winner": "b",
    }


def test_the_draw_cannot_be_rewritten_once_published(
    client: Client, tied_poll: Poll, admin_user: User
) -> None:
    """§8.3: the draw is entered before publication, never after — once the
    winner it names is public, a second draw must not silently replace it."""
    client.force_login(admin_user)
    client.post(_url(tied_poll), {"action": "record_tiebreak", "order": ["b", "c", "a"]})
    client.post(_url(tied_poll), {"confirmed": "1", "action": "publish"})

    response = client.post(_url(tied_poll), {"action": "record_tiebreak", "order": ["c", "a", "b"]})
    assert response.status_code == 200
    assert "scrutin clos" in response.content.decode()

    tied_poll.refresh_from_db()
    assert tied_poll.physical_tiebreak_order == ["b", "c", "a"]
    assert AuditEvent.objects.filter(action=Action.TIEBREAK_ENTERED, poll=tied_poll).count() == 1

    document = json.loads(client.get(_url(tied_poll) + "?format=json").content)
    assert document["winner"] == "b"


def test_a_draw_that_is_not_a_permutation_of_the_tie_is_refused(
    client: Client, tied_poll: Poll, admin_user: User
) -> None:
    client.force_login(admin_user)
    response = client.post(_url(tied_poll), {"action": "record_tiebreak", "order": ["b", "b", "a"]})
    assert response.status_code == 200
    assert "chaque proposition à égalité" in response.content.decode()

    tied_poll.refresh_from_db()
    assert tied_poll.physical_tiebreak_order == []
    assert not AuditEvent.objects.filter(action=Action.TIEBREAK_ENTERED).exists()


def test_the_override_reason_from_closure_is_shown(client: Client, admin_user: User) -> None:
    """§9 / T-19: closure forced past a pending countersign carries its reason
    onto this screen, where it also travels into the publication."""
    from apps.ballots.models import BallotStatus

    poll = _make_poll()
    force_open(poll)
    _cast(poll, ([["a"], ["b"], ["c"]],))
    Ballot.objects.create(
        poll=poll,
        tracking_code=new_tracking_code(),
        ranking=[["c"], ["b"], ["a"]],
        source=BallotSource.PAPER,
        status=BallotStatus.PENDING_COUNTERSIGN,
    )
    close_poll(
        poll,
        override_reason=Reason.COUNTERSIGN_UNAVAILABLE,
        early_reason=Reason.ADMINISTRATIVE_DECISION,
    )
    _grant(poll, admin_user)
    client.force_login(admin_user)

    body = client.get(_url(poll)).content.decode()
    assert Reason.COUNTERSIGN_UNAVAILABLE in body


# --- formal reconciliation (R-8.6, docs/specification-decision-log.md #16) -----


@pytest.fixture
def reconciliation_poll(admin_user: User) -> Poll:
    """Open, ``paper_requires_reconciliation`` set, ``paper_entry_deadline``
    already passed — the reconciliation form is immediately actionable."""
    now = timezone.now()
    poll = Poll.objects.create(
        title_i18n={"fr": "Rapprochement"},
        description_i18n={"fr": "Trois propositions."},
        languages=["fr"],
        opens_at=now - timedelta(days=2),
        closes_at=now - timedelta(hours=1),
        paper_entry_deadline=now - timedelta(hours=1),
        paper_requires_reconciliation=True,
    )
    for position, option_id in enumerate(["a", "b", "c"]):
        PollOption.objects.create(
            poll=poll, option_id=option_id, label_i18n={"fr": option_id.upper()}, position=position
        )
    WorkingRollEntry.objects.create(
        birth_name="Bernard",
        first_names="Julie",
        date_of_birth="03/03/1990",
        date_of_birth_parsed="1990-03-03",
        list_types=["principale"],
    )
    force_open(poll)
    _grant(poll, admin_user)
    return Poll.objects.get(pk=poll.pk)


def test_the_admin_sees_the_reconciliation_form_while_open(
    client: Client, reconciliation_poll: Poll, admin_user: User
) -> None:
    client.force_login(admin_user)
    body = client.get(_url(reconciliation_poll)).content.decode()
    assert 'name="action" value="record_reconciliation"' in body
    assert "Ce qui bloquerait la clôture" in body
    assert "rapprochement" in body.lower()


def test_recording_it_clears_the_closure_blocker_and_archives_the_counts(
    client: Client, reconciliation_poll: Poll, admin_user: User
) -> None:
    from apps.audit.models import Action as AuditAction
    from apps.ballots.models import ReconciliationRecord
    from apps.elections.transitions import closing_blockers

    client.force_login(admin_user)
    assert "reconciliation_pending" in closing_blockers(reconciliation_poll)

    response = client.post(
        _url(reconciliation_poll),
        {
            "confirmed": "1",
            "action": "record_reconciliation",
            "forms_retained_count": "3",
            "note": "RAS",
        },
    )
    assert response.status_code == 302

    record = ReconciliationRecord.objects.get(poll=reconciliation_poll)
    assert record.forms_retained_count == 3
    assert record.recorded_ballots_count == 0
    assert record.signed_by == admin_user
    assert AuditEvent.objects.filter(
        action=AuditAction.RECONCILIATION_RECORDED, poll=reconciliation_poll
    ).exists()

    reconciliation_poll.refresh_from_db()
    assert "reconciliation_pending" not in closing_blockers(reconciliation_poll)

    body = client.get(_url(reconciliation_poll)).content.decode()
    assert "Rapprochement enregistré" in body
    assert 'name="action" value="record_reconciliation"' not in body

    closed = close_poll(reconciliation_poll, early_reason=Reason.ADMINISTRATIVE_DECISION)
    assert closed.state == PollState.CLOSED


def test_an_auditor_cannot_record_the_reconciliation(
    client: Client, reconciliation_poll: Poll, db: None
) -> None:
    auditor = User.objects.create_user(username="aud.r", password="x", full_name="Aud R")
    PollRole.objects.create(poll=reconciliation_poll, user=auditor, role=Role.AUDITOR)
    client.force_login(auditor)

    body = client.get(_url(reconciliation_poll)).content.decode()
    assert 'name="action" value="record_reconciliation"' not in body

    response = client.post(
        _url(reconciliation_poll),
        {"confirmed": "1", "action": "record_reconciliation", "forms_retained_count": "0"},
    )
    assert response.status_code == 403
