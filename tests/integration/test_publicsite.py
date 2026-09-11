# SPDX-License-Identifier: 0BSD
"""The public poll page and results page (§6.6, §9).

What they must get right: a draft or sandbox poll is invisible (INV-8, §6.6); a
running count appears only where ``show_live_participation`` is set and nowhere
otherwise (R-11.5, T-20); an extension of the closing date shows on the page
(R-3.4, T-5); and the published results — page, CSV and JSON — are exactly the
live ballot set and the §9 document, so the closure hash recomputes from the
CSV alone and the three artefacts cross-check (R-11.2, R-11.4, T-36).
"""

from __future__ import annotations

import csv
import io
import json
from datetime import timedelta

import pytest
from django.db import transaction
from django.test import Client
from django.utils import timezone

from apps.audit.models import Reason
from apps.ballots.models import Ballot, BallotSource, BallotStatus
from apps.core.canonical import CanonicalBallot, closure_hash
from apps.core.codes import new_tracking_code
from apps.core.models import User
from apps.core.types import TrackingCode
from apps.elections import closure
from apps.elections.closure import live_ballots
from apps.elections.models import Poll, PollOption, WorkingRollEntry
from apps.elections.transitions import (
    TransitionRefused,
    announce_poll,
    close_poll,
    extend_closes_at,
    open_poll,
    publish_poll,
)
from apps.registrations.models import Channel, Registration, RegistrationState


def _make_poll(*, show_live: bool = False, sandbox: bool = False) -> Poll:
    now = timezone.now()
    poll = Poll.objects.create(
        title_i18n={"fr": "Aménagement de la place"},
        description_i18n={"fr": "Trois propositions au choix."},
        languages=["fr"],
        opens_at=now - timedelta(days=1),
        closes_at=now + timedelta(days=1),
        paper_entry_deadline=now + timedelta(days=1),
        show_live_participation=show_live,
        is_sandbox=sandbox,
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


def _register(poll: Poll, tag: str, *, channel: str = Channel.NONE) -> None:
    Registration.objects.create(
        poll=poll,
        declared_last_name="Dupont",
        declared_first_names="Émile",
        declared_dob="12/05/1970",
        email=f"{tag}@example.fr",
        email_canonical=f"{tag}@example.fr",
        state=RegistrationState.ACTIVE,
        channel=channel,
    )


def _cast(poll: Poll, rankings: list[list[list[str]]]) -> None:
    for ranking in rankings:
        Ballot.objects.create(
            poll=poll,
            tracking_code=new_tracking_code(),
            ranking=ranking,
            source=BallotSource.ONLINE,
        )


@pytest.fixture
def open_poll_fixture(db: None) -> Poll:
    poll = _make_poll()
    open_poll(poll)
    return Poll.objects.get(pk=poll.pk)


@pytest.fixture
def published_poll(db: None) -> Poll:
    poll = _make_poll()
    open_poll(poll)
    _register(poll, "voter1", channel=Channel.ONLINE)
    _cast(poll, [[["a"], ["b"], ["c"]], [["a"], ["b"], ["c"]]])
    close_poll(poll)
    publish_poll(poll, User.objects.create_user(username="p.admin", password="x"))
    return Poll.objects.get(pk=poll.pk)


# --- the poll page: visibility (§6.6, INV-8) ----------------------------


def test_a_draft_poll_is_not_public(client: Client, db: None) -> None:
    poll = _make_poll()  # never opened
    assert client.get(f"/fr/scrutin/{poll.pk}/").status_code == 404


def test_a_sandbox_poll_is_not_public(client: Client, db: None) -> None:
    poll = _make_poll(sandbox=True)
    open_poll(poll)
    assert client.get(f"/fr/scrutin/{poll.pk}/").status_code == 404
    assert poll.pk  # sanity


def test_the_open_poll_page_shows_the_propositions_and_calendar(
    client: Client, open_poll_fixture: Poll
) -> None:
    body = client.get(f"/fr/scrutin/{open_poll_fixture.pk}/").content.decode()
    assert "Aménagement de la place" in body
    assert "A" in body and "B" in body and "C" in body
    assert "Clôture du vote en ligne" in body
    # R-1.4: the consultative-status statement with the CGCT article reference.
    assert "L1112-15" in body
    # An open poll points the reader at registration.
    assert f"/fr/inscription/{open_poll_fixture.pk}/" in body


def test_a_closed_unpublished_poll_says_the_tally_is_under_way(client: Client, db: None) -> None:
    poll = _make_poll()
    open_poll(poll)
    close_poll(poll)
    body = client.get(f"/fr/scrutin/{poll.pk}/").content.decode()
    assert "dépouillement" in body.lower()
    assert f"/fr/scrutin/{poll.pk}/resultats/" not in body


def test_a_published_poll_page_links_to_the_results(client: Client, published_poll: Poll) -> None:
    body = client.get(f"/fr/scrutin/{published_poll.pk}/").content.decode()
    assert f"/fr/scrutin/{published_poll.pk}/resultats/" in body


# --- participation: shown only where configured (R-11.5, T-20) ---------


def test_turnout_is_absent_by_default(client: Client, open_poll_fixture: Poll) -> None:
    _register(open_poll_fixture, "v1", channel=Channel.ONLINE)
    _register(open_poll_fixture, "v2", channel=Channel.PAPER)
    _register(open_poll_fixture, "v3")
    body = client.get(f"/fr/scrutin/{open_poll_fixture.pk}/").content.decode()
    assert "Participation" not in body
    assert "Bulletins déposés" not in body


def test_turnout_is_shown_when_the_flag_is_set(client: Client, db: None) -> None:
    poll = _make_poll(show_live=True)
    open_poll(poll)
    _register(poll, "v1", channel=Channel.ONLINE)
    _register(poll, "v2", channel=Channel.ONLINE)
    _register(poll, "v3", channel=Channel.PAPER)
    _register(poll, "v4")
    body = client.get(f"/fr/scrutin/{poll.pk}/").content.decode()
    assert "Participation" in body
    assert "Bulletins déposés" in body


def test_no_running_count_leaks_once_the_poll_is_closed(client: Client, db: None) -> None:
    """R-11.5 / §9: after closure the figures belong to the publication, not
    this page — which for a closed-but-unpublished poll means nothing here."""
    poll = _make_poll(show_live=True)
    open_poll(poll)
    _register(poll, "v1", channel=Channel.ONLINE)
    close_poll(poll)
    body = client.get(f"/fr/scrutin/{poll.pk}/").content.decode()
    assert "Bulletins déposés" not in body


# --- extension of the closing date (R-3.4, T-5) -----------------------


def test_a_logged_extension_appears_on_the_page(client: Client, db: None) -> None:
    poll = _make_poll()
    open_poll(poll)
    actor = User.objects.create_user(username="p.admin", password="x", full_name="P. Admin")
    extend_closes_at(
        Poll.objects.get(pk=poll.pk),
        timezone.now() + timedelta(days=5),
        actor,
        Reason.ADMINISTRATIVE_DECISION,
    )
    body = client.get(f"/fr/scrutin/{poll.pk}/").content.decode()
    assert "Report de la clôture" in body
    assert "Clôture repoussée" in body
    assert str(Reason.ADMINISTRATIVE_DECISION.label) in body
    # R-3.4 is about the fact and the reason, not the operator.
    assert "P. Admin" not in body


# --- the results page (§9, R-11.2/4) ----------------------------------


def test_results_are_404_until_published(client: Client, db: None) -> None:
    poll = _make_poll()
    open_poll(poll)
    close_poll(poll)
    assert client.get(f"/fr/scrutin/{poll.pk}/resultats/").status_code == 404


def test_a_sandbox_published_poll_has_no_public_results(client: Client, db: None) -> None:
    poll = _make_poll(sandbox=True)
    open_poll(poll)
    _cast(poll, [[["a"], ["b"], ["c"]]])
    close_poll(poll)
    publish_poll(poll, User.objects.create_user(username="p.admin", password="x"))
    assert client.get(f"/fr/scrutin/{poll.pk}/resultats/").status_code == 404


def test_the_results_page_shows_the_derivation_and_hash(
    client: Client, published_poll: Poll
) -> None:
    body = client.get(f"/fr/scrutin/{published_poll.pk}/resultats/").content.decode()
    assert published_poll.closure_hash is not None
    assert bytes(published_poll.closure_hash).hex() in body
    assert "Matrice des préférences" in body
    assert "Participation, figée à la clôture" in body
    assert "?format=csv" in body
    assert "?format=json" in body
    assert "L1112-15" in body


def test_the_published_csv_is_the_live_set_and_recomputes_the_hash(
    client: Client, published_poll: Poll
) -> None:
    response = client.get(f"/fr/scrutin/{published_poll.pk}/resultats/?format=csv")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert published_poll.closure_hash is not None
    assert bytes(published_poll.closure_hash) == closure_hash(live_ballots(published_poll))


def test_the_published_json_is_the_publication_document(
    client: Client, published_poll: Poll
) -> None:
    response = client.get(f"/fr/scrutin/{published_poll.pk}/resultats/?format=json")
    document = json.loads(response.content)
    assert published_poll.closure_hash is not None
    assert document["closure_hash"] == bytes(published_poll.closure_hash).hex()
    assert document["winner"] == "a"


def test_t36_published_artefacts_cross_check(client: Client, db: None) -> None:
    """T-36: the three published artefacts agree, on a poll with a non-trivial
    mix — both channels, superseded versions, non-voters and one unconfirmed
    registration.

    Two identities (§9, R-11.2/4):

    * *CSV row count = live set = hashed set.* The CSV carries one row per
      ``live`` ballot and no other; the superseded rows beside them reach
      neither the CSV nor the hash, which recomputes from the CSV alone.
    * *registered = online + paper + non-voters.* The counts frozen at closure
      reconcile, and are drawn from the ``active`` registrations only — a
      ``pending_email`` one is not a registrant yet (R-5.5, T-27).
    """
    poll = _make_poll()
    open_poll(poll)
    poll = Poll.objects.get(pk=poll.pk)

    # Registrations, by channel. The platform never joins these to a ballot
    # (INV-1); the figures below are counted from ``channel`` alone.
    for i in range(5):
        _register(poll, f"online{i}", channel=Channel.ONLINE)
    for i in range(2):
        _register(poll, f"paper{i}", channel=Channel.PAPER)
    for i in range(3):
        _register(poll, f"abstention{i}")  # active, channel = none
    Registration.objects.create(
        poll=poll,
        declared_last_name="Dupont",
        declared_first_names="Émile",
        declared_dob="12/05/1970",
        email="pending@example.fr",
        email_canonical="pending@example.fr",
        state=RegistrationState.PENDING_EMAIL,
        channel=Channel.NONE,
    )

    # The live ballot set: five online, two paper. One online ballot was
    # modified once and one paper ballot corrected once, leaving two superseded
    # rows that share their code with the live version that replaced them.
    live_codes: set[str] = set()

    def _live(code: str, ranking: list[list[str]], source: str, version: int = 1) -> None:
        live_codes.add(code)
        Ballot.objects.create(
            poll=poll,
            tracking_code=code,
            version=version,
            ranking=ranking,
            source=source,
            status=BallotStatus.LIVE,
        )

    for _i in range(4):
        _live(new_tracking_code(), [["a"], ["b"], ["c"]], BallotSource.ONLINE)
    _live(new_tracking_code(), [["b"], ["a"], ["c"]], BallotSource.PAPER)

    modified = new_tracking_code()
    Ballot.objects.create(
        poll=poll,
        tracking_code=modified,
        version=1,
        ranking=[["c"], ["b"], ["a"]],
        source=BallotSource.ONLINE,
        status=BallotStatus.SUPERSEDED,
    )
    _live(modified, [["a"], ["c"], ["b"]], BallotSource.ONLINE, version=2)

    corrected = new_tracking_code()
    Ballot.objects.create(
        poll=poll,
        tracking_code=corrected,
        version=1,
        ranking=[["c"], ["a"], ["b"]],
        source=BallotSource.PAPER,
        status=BallotStatus.SUPERSEDED,
    )
    _live(corrected, [["b"], ["c"], ["a"]], BallotSource.PAPER, version=2)

    close_poll(poll)
    publish_poll(poll, User.objects.create_user(username="p.admin", password="x"))
    poll = Poll.objects.get(pk=poll.pk)

    csv_text = client.get(f"/fr/scrutin/{poll.pk}/resultats/?format=csv").content.decode()
    document = json.loads(client.get(f"/fr/scrutin/{poll.pk}/resultats/?format=json").content)

    rows = list(csv.reader(io.StringIO(csv_text)))
    assert rows[0] == ["tracking_code", "ranking"]
    data = rows[1:]

    # CSV row count = live set = hashed set.
    live = Ballot.live.filter(poll=poll)
    assert len(data) == live.count() == len(live_ballots(poll)) == document["ballot_count"] == 7
    assert {code for code, _ranking in data} == live_codes
    recomputed = closure_hash(
        CanonicalBallot(TrackingCode(code), json.loads(ranking)) for code, ranking in data
    )
    assert poll.closure_hash is not None
    assert recomputed == bytes(poll.closure_hash) == bytes.fromhex(document["closure_hash"])

    # The superseded versions are gone from every artefact: the modified code
    # appears once, carrying its v2 ranking, not v1's.
    by_code = {code: json.loads(ranking) for code, ranking in data}
    assert by_code[modified] == [["a"], ["c"], ["b"]]
    assert by_code[corrected] == [["b"], ["c"], ["a"]]

    # registered = online + paper + non-voters, over the active registrations.
    counts = document["counts"]
    assert counts == poll.frozen_counts
    assert counts["registered"] == (
        counts["ballots_online"] + counts["ballots_paper"] + counts["non_voters"]
    )
    assert (counts["ballots_online"], counts["ballots_paper"], counts["non_voters"]) == (5, 2, 3)
    assert counts["registered"] == 10
    assert Registration.objects.filter(poll=poll, state=RegistrationState.ACTIVE).count() == 10


# --- T-23: labels never move the hash or the result ------------------


#: Pinned tracking codes and rankings, so two polls that differ only in their
#: option labels have a byte-identical canonical serialisation (§9).
_T23_BALLOTS = [
    ("TRACKAAAA1", [["a"], ["b"], ["c"]]),
    ("TRACKBBBB2", [["a"], ["c"], ["b"]]),
    ("TRACKCCCC3", [["b"], ["a"], ["c"]]),
]


def _publish_with_labels(labels: dict[str, dict[str, str]]) -> Poll:
    poll = _make_poll()
    for option in poll.options.all():
        # Still ``draft`` here, so the INV-6 option trigger permits the write.
        option.label_i18n = labels[option.option_id]
        option.save(update_fields=["label_i18n"])
    open_poll(poll)
    poll = Poll.objects.get(pk=poll.pk)
    for code, ranking in _T23_BALLOTS:
        Ballot.objects.create(
            poll=poll, tracking_code=code, ranking=ranking, source=BallotSource.ONLINE
        )
    close_poll(poll)
    publish_poll(poll, User.objects.create_user(username=f"admin-{poll.pk}", password="x"))
    return Poll.objects.get(pk=poll.pk)


def test_t23_labels_are_frozen_and_the_hash_and_result_are_built_from_ids(db: None) -> None:
    """T-23 / §3.8 / R-10.7: option labels are configuration, frozen when the
    poll opens (R-3.3, INV-6) — there is no path to add or correct a translation
    once a poll has left ``draft``, and a ``label_i18n`` write past ``draft`` is
    refused at the database.

    Nothing is lost by that: the closure hash and the tally are functions of
    option ids and tracking codes only. Two polls identical but for their
    labels — ballots and tracking codes pinned equal — publish the same hash and
    the same winner, matrix and derivation; only the ``options`` lookup table
    differs.
    """
    plain = _publish_with_labels(
        {"a": {"fr": "A"}, "b": {"fr": "B"}, "c": {"fr": "C"}},
    )
    reworded = _publish_with_labels(
        {
            "a": {"fr": "La place réaménagée"},
            "b": {"fr": "Un parc arboré"},
            "c": {"fr": "Un parking silo"},
        },
    )

    assert plain.closure_hash is not None
    assert reworded.closure_hash is not None
    assert bytes(plain.closure_hash) == bytes(reworded.closure_hash)
    assert bytes(plain.closure_hash) == closure_hash(live_ballots(plain))

    doc_plain = closure.publication(plain)
    doc_reworded = closure.publication(reworded)
    for key in (
        "closure_hash",
        "winner",
        "matrix",
        "derivation",
        "ballot_count",
        "serialisation_bytes",
        "orderings",
    ):
        assert doc_plain[key] == doc_reworded[key], key
    # The one thing that does differ is the label lookup table.
    assert doc_plain["options"] != doc_reworded["options"]
    assert doc_reworded["options"]["a"] == {"fr": "La place réaménagée"}

    # And a label edit past ``draft`` is refused at the database — the labels a
    # voter ranked cannot be rewritten after the fact (R-3.3, INV-6).
    option = plain.options.get(option_id="a")
    option.label_i18n = {"fr": "A — libellé corrigé"}
    with pytest.raises(Exception, match="INV-6"), transaction.atomic():
        option.save(update_fields=["label_i18n"])
    assert PollOption.objects.get(pk=option.pk).label_i18n == {"fr": "A"}
    reloaded = Poll.objects.get(pk=plain.pk)
    assert reloaded.closure_hash is not None
    assert bytes(reloaded.closure_hash) == bytes(plain.closure_hash)


def test_an_unknown_format_is_404(client: Client, published_poll: Poll) -> None:
    assert client.get(f"/fr/scrutin/{published_poll.pk}/resultats/?format=pdf").status_code == 404


# --- early preview: the `announced` state (R-3.10, T-69) ------------------


def test_a_draft_poll_never_appears_even_short_of_two_options(client: Client, db: None) -> None:
    """A ``draft`` poll is never public, under no configuration — there is no
    flag to flip; the only way to become public is to actually transition
    (``announce_poll``), and that transition itself refuses a poll not ready
    to be shown (fewer than two propositions, R-3.10)."""
    poll = _make_poll()  # never announced
    assert client.get(f"/fr/scrutin/{poll.pk}/").status_code == 404
    assert poll.title() not in client.get("/fr/").content.decode()

    poll.options.exclude(option_id="a").delete()
    with pytest.raises(TransitionRefused):
        announce_poll(poll)
    poll.refresh_from_db()
    assert poll.state == "draft"
    assert client.get(f"/fr/scrutin/{poll.pk}/").status_code == 404


def test_an_announced_poll_previews_publicly(client: Client, db: None) -> None:
    poll = _make_poll()
    announce_poll(poll)
    poll = Poll.objects.get(pk=poll.pk)

    listing = client.get("/fr/").content.decode()
    assert "Aménagement de la place" in listing
    assert "à venir" in listing

    body = client.get(f"/fr/scrutin/{poll.pk}/").content.decode()
    assert "Aménagement de la place" in body
    assert "A" in body and "B" in body and "C" in body
    assert "n'est pas encore ouvert" in body
    # A preview offers no way to register or vote — nothing behind it would
    # accept a submission before the poll actually opens (§5.1).
    assert f"/fr/inscription/{poll.pk}/" not in body
    # No participation either: `_live_participation` only computes for `open`.
    assert "Participation" not in body

    # `open_poll` accepts `announced` exactly as it accepts `draft` (R-3.10).
    open_poll(poll)
    poll.refresh_from_db()
    assert poll.state == "open"
    assert client.get(f"/fr/scrutin/{poll.pk}/").status_code == 200


def test_a_sandbox_poll_stays_hidden_even_once_announced(client: Client, db: None) -> None:
    """INV-8: ``announced`` cannot make a sandbox poll public."""
    poll = _make_poll(sandbox=True)
    announce_poll(poll)
    poll.refresh_from_db()
    assert poll.state == "announced"
    assert client.get(f"/fr/scrutin/{poll.pk}/").status_code == 404
    assert poll.title() not in client.get("/fr/").content.decode()
